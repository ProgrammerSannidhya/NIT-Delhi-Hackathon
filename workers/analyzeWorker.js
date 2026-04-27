import { Worker } from "bullmq";
import { connection } from "../configs/queue.js";

import { cloneRepo } from "../utils/clonerepo.js";
import { deleteRepo } from "../utils/deleterepo.js";
import { runScanner } from "../utils/runscan.js";

import {
updateAnalysis,
getAnalysisById
} from "../models/analyzeModel.js";

import { upsertRepoCache } from "../models/repoCacheModel.js";

import { prepareGit, commitAndPush } from "../utils/gitHelper.js";
import { forkRepo, createPullRequest } from "../utils/githubHelper.js";

import fs from "fs";
import path from "path";

console.log("Worker starting");

/* ================= SCAN ================= */
const handleScan = async (job) => {
const { analysisId, repoLink, userType, branch, commitSha } = job.data;

    
let repoPath;

try {
    console.log("SCAN START:", analysisId, "Attempt:", job.attemptsMade + 1);

    await updateAnalysis(analysisId, { status: "processing" });

    repoPath = await cloneRepo(repoLink);

    const result = await runScanner(repoPath, userType);

    await updateAnalysis(analysisId, {
        result,
        status: "waiting_for_user",
        commit_sha: commitSha,
        branch
    });

    /* ===== VALID CACHE WRITE ===== */
    const hasSignal =
        result?.unusedFiles?.length ||
        result?.unusedDeps?.length ||
        result?.unusedExports?.length;

    if (hasSignal) {
        try {
            await upsertRepoCache(repoLink, branch, commitSha, result);
            console.log("CACHE STORED:", analysisId);
        } catch (cacheErr) {
            console.error("CACHE ERROR (ignored):", cacheErr.message);
        }
    } else {
        console.log("SKIP CACHE (empty result):", analysisId);
    }

    console.log("SCAN DONE:", analysisId);

} catch (err) {
    console.error("SCAN ERROR:", analysisId, err.message);

    /* ===== FINAL FAILURE AFTER 3 ATTEMPTS ===== */
    if (job.attemptsMade >= 2) {
        console.log("FINAL FAILURE:", analysisId);

        await updateAnalysis(analysisId, {
            status: "failed"
        });
    }

    throw err;

} finally {
    if (repoPath && fs.existsSync(repoPath)) {
        deleteRepo(repoPath);
    }
}
    

};

/* ================= APPLY ================= */
const handleApply = async (job) => {
const { analysisId, files = [], deps = [] } = job.data;

    
let repoPath;

try {
    console.log("APPLY START:", analysisId, "Attempt:", job.attemptsMade + 1);

    const analysis = await getAnalysisById(analysisId);
    if (!analysis) throw new Error("Analysis not found");

    /* ===== PREVENT DUPLICATE PR ===== */
    if (analysis.pr_url) {
        console.log("PR already exists, skipping:", analysisId);
        return;
    }

    await updateAnalysis(analysisId, {
        status: "applying_changes"
    });

    const forkUrl = await forkRepo(analysis.repo_url);
    repoPath = await cloneRepo(forkUrl);

    /* delete files */
    for (const file of files) {
        const fullPath = path.join(repoPath, file);
        if (fs.existsSync(fullPath)) {
            fs.rmSync(fullPath, { recursive: true, force: true });
        }
    }

    /* remove dependencies */
    const pkgPath = path.join(repoPath, "package.json");

    if (fs.existsSync(pkgPath)) {
        const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf-8"));

        for (const dep of deps) {
            delete pkg.dependencies?.[dep];
            delete pkg.devDependencies?.[dep];
        }

        fs.writeFileSync(pkgPath, JSON.stringify(pkg, null, 2));
    }

    const { git, branch } = await prepareGit(repoPath, analysisId);

    await commitAndPush(git, branch);

    const prUrl = await createPullRequest({
        repoUrl: analysis.repo_url,
        branch,
        analysisId
    });

    await updateAnalysis(analysisId, {
        status: "completed",
        pr_url: prUrl
    });

    console.log("APPLY DONE:", analysisId);

} catch (err) {
    console.error("APPLY ERROR:", analysisId, err.message);

    if (job.attemptsMade >= 2) {
        console.log("FINAL APPLY FAILURE:", analysisId);

        await updateAnalysis(analysisId, {
            status: "apply_failed"
        });
    }

    throw err;

} finally {
    if (repoPath && fs.existsSync(repoPath)) {
        deleteRepo(repoPath);
    }
}
    

};


/* ================= WORKER ================= */
const worker = new Worker(
"analysisQueue",
async (job) => {
console.log("JOB RECEIVED:", job.name, job.id);

    
    if (job.name === "scan") return await handleScan(job);
    if (job.name === "apply") return await handleApply(job);

    throw new Error("Unknown job type");
},
{
    connection,
    concurrency: 5
}
    

);

/* ================= EVENTS ================= */
worker.on("active", (job) => {
console.log("PROCESSING:", job.id);
});

worker.on("completed", (job) => {
console.log("COMPLETED:", job.id);
});

worker.on("failed", (job, err) => {
console.error("FAILED:", job?.id, err.message);
});

worker.on("error", (err) => {
console.error("WORKER ERROR:", err);
});
