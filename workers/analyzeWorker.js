import { Worker } from "bullmq";
import { connection } from "../configs/queue.js";

import { cloneRepo } from "../utils/clonerepo.js";
import {deleteRepo} from "../utils/deleterepo.js";
import { runScanner } from "../utils/runscan.js";

import { updateAnalysis } from "../models/analyzeModel.js";
import { upsertRepoCache } from "../models/repoCacheModel.js";

import { filterResults } from "../services/decisionServices.js";

import fs from "fs";
import path from "path";

const isValidResult = (result) => {
if (!result || result.error) return false;


const total =
    (result.unusedFiles?.length || 0) +
    (result.unusedExports?.length || 0) +
    (result.unusedDeps?.length || 0);

return total > 0;


};

const worker = new Worker(
"analysisQueue",
async (job) => {
const {
analysisId,
repoLink,
userType,
branch,
commitSha
} = job.data;


    let repoPath;

    try {
        console.log("JOB RECEIVED:", analysisId);

        await updateAnalysis(analysisId, {
            status: "processing"
        });

        repoPath = await cloneRepo(repoLink);

        console.log("CLONED PATH:", repoPath);
        console.log("TYPE:", typeof repoPath);

        // 🔴 catch Promise bug early
        if (typeof repoPath !== "string") {
            throw new Error("cloneRepo returned non-string (Promise bug)");
        }

        const absolutePath = path.resolve(repoPath);

        if (!fs.existsSync(absolutePath)) {
            throw new Error("Repo path does not exist: " + absolutePath);
        }

        console.log("RUNNING SCANNER ON:", absolutePath);

        const result = await runScanner(absolutePath, userType);

        console.log("SCANNER DONE");

        // 🔴 DO NOT CACHE BAD RESULTS
        if (!isValidResult(result)) {
            throw new Error("Invalid/empty result → skip cache");
        }

        const filtered = filterResults(result);

        await updateAnalysis(analysisId, {
            result,
            filtered_result: filtered,
            status: "waiting_for_user",
            commit_sha: commitSha,
            branch
        });

        console.log("DB UPDATED");

        await upsertRepoCache(
            repoLink,
            branch,
            commitSha,
            result
        );

        console.log("CACHE UPDATED");

    } catch (err) {
        console.error("WORKER ERROR:", err);

        await updateAnalysis(analysisId, {
            status: "failed"
        });

    } finally {
        if (repoPath && fs.existsSync(repoPath)) {
            deleteRepo(repoPath);
            console.log("CLEANED UP:", repoPath);
        }
    }
},
{ connection }


);

worker.on("completed", (job) => {
console.log("JOB COMPLETED:", job.id);
});

worker.on("failed", (job, err) => {
console.error("JOB FAILED:", job?.id, err);
});

export default worker;
