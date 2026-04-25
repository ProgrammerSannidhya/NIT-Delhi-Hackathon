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

import {
    findExistingPR,
    createPRRecord
} from "../models/repoPRModel.js";

import fs from "fs";
import path from "path";

/* ---------------- VALIDATION ---------------- */
const isValidResult = (result) => {
    if (!result || result.error) return false;

    const total =
        (result.unusedFiles?.length || 0) +
        (result.unusedExports?.length || 0) +
        (result.unusedDeps?.length || 0);

    return total > 0;
};

/* ---------------- SCAN ---------------- */
const handleScan = async (job) => {
    const { analysisId, repoLink, userType, branch, commitSha } = job.data;

    let repoPath;

    try {
        await updateAnalysis(analysisId, { status: "processing" });

        repoPath = await cloneRepo(repoLink);

        const result = await runScanner(repoPath, userType);

        if (!isValidResult(result)) {
            throw new Error("Invalid result");
        }

        await updateAnalysis(analysisId, {
            result,
            filtered_result: null,
            status: "waiting_for_user",
            commit_sha: commitSha,
            branch
        });

        await upsertRepoCache(repoLink, branch, commitSha, result);

    } catch (err) {
        console.error("SCAN ERROR:", err);

        await updateAnalysis(analysisId, {
            status: "failed"
        });

    } finally {
        if (repoPath && fs.existsSync(repoPath)) {
            deleteRepo(repoPath);
        }
    }
};

/* ---------------- APPLY ---------------- */
const handleApply = async (job) => {
    const { analysisId, files = [], deps = [] } = job.data;

    let repoPath;

    try {
        await updateAnalysis(analysisId, {
            status: "applying_changes"
        });

        const analysis = await getAnalysisById(analysisId);

        /* 🔴 CHECK EXISTING PR */
        const existing = await findExistingPR(
            analysis.repo_url,
            analysis.commit_sha
        );

        if (existing) {
            console.log("PR already exists:", existing.pr_url);

            await updateAnalysis(analysisId, {
                status: "completed",
                pr_url: existing.pr_url
            });

            return;
        }

        /* 🔴 FORK */
        const forkUrl = await forkRepo(analysis.repo_url);

        /* 🔴 CLONE */
        repoPath = await cloneRepo(forkUrl);

        console.log("CLONED FOR APPLY:", repoPath);

        /* 🔴 DELETE FILES */
        for (let file of files) {
            if (file.includes("/repos/")) {
                const parts = file.split("/repos/");
                file = parts[1].split("/").slice(1).join("/");
            }

            const fullPath = path.join(repoPath, file);

            if (fs.existsSync(fullPath)) {
                fs.rmSync(fullPath, { recursive: true, force: true });
                console.log("DELETED:", fullPath);
            }
        }

        /* 🔴 DEP CLEANUP */
        const pkgPath = path.join(repoPath, "package.json");

        if (fs.existsSync(pkgPath)) {
            const pkg = JSON.parse(fs.readFileSync(pkgPath));

            let changed = false;

            for (const dep of deps) {
                if (pkg.dependencies?.[dep]) {
                    delete pkg.dependencies[dep];
                    changed = true;
                }
                if (pkg.devDependencies?.[dep]) {
                    delete pkg.devDependencies[dep];
                    changed = true;
                }
            }

            if (changed) {
                fs.writeFileSync(pkgPath, JSON.stringify(pkg, null, 2));
            }
        }

        /* 🔴 GIT */
        const { git, branch } = await prepareGit(repoPath, analysisId);

        const pushedBranch = await commitAndPush(git, branch);

        if (!pushedBranch) {
            throw new Error("No changes → skipping PR");
        }

        /* 🔴 CREATE PR */
        const prUrl = await createPullRequest({
            repoUrl: analysis.repo_url,
            branch,
            analysisId,
            base: analysis.branch || "main"
        });

        /* 🔴 SAVE PR RECORD */
        await createPRRecord({
            repoUrl: analysis.repo_url,
            commitSha: analysis.commit_sha,
            forkUrl,
            branch,
            prUrl
        });

        await updateAnalysis(analysisId, {
            status: "completed",
            pr_url: prUrl
        });

    } catch (err) {
        console.error("APPLY ERROR:", err);

        await updateAnalysis(analysisId, {
            status: "apply_failed"
        });

    } finally {
        if (repoPath && fs.existsSync(repoPath)) {
            deleteRepo(repoPath);
        }
    }
};

/* ---------------- WORKER ---------------- */
const worker = new Worker(
    "analysisQueue",
    async (job) => {
        if (job.name === "scan") return handleScan(job);
        if (job.name === "apply") return handleApply(job);
    },
    { connection }
);

export default worker;