import { Worker } from "bullmq";
import IORedis from "ioredis";

import cloneRepo from "../utils/clonerepo.js";
import deleteRepo from "../utils/deleterepo.js";
import { runScanner } from "../utils/runscan.js";

import {
    updateAnalysis,
    markFailed
} from "../models/analyzeModel.js";

import {
    upsertRepoCache
} from "../models/repoCacheModel.js";

/* ================= REDIS CONNECTION ================= */
const connection = new IORedis({
    host: process.env.REDIS_HOST || "redis",
    port: process.env.REDIS_PORT || 6379,
    maxRetriesPerRequest: null
});
/* ================= WORKER ================= */
new Worker(
    "analysis",
    async job => {
        const { repoLink, analysisId, userType } = job.data;

        let repoPath;

        try {
            repoPath = await cloneRepo(repoLink);

            const result = await runScanner(repoPath, userType);

            await updateAnalysis(analysisId, result);

            await upsertRepoCache(repoLink, result);

        } catch (err) {
            await markFailed(analysisId, err.message);
        } finally {
            if (repoPath) deleteRepo(repoPath);
        }
    },
    { connection }
);