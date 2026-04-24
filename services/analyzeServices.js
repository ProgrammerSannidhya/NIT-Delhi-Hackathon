import {
    createAnalysis,
    getAnalysisById,
    getAnalysesByUser
} from "../models/analyzeModel.js";

import {
    findRepoCache
} from "../models/repoCacheModel.js";

import { analysisQueue } from "../configs/queue.js";

const normalizeRepo = (url) =>
    url.trim().toLowerCase().replace(/\.git$/, "").replace(/\/$/, "");

export const startAnalysis = async (userId, repoLink, userType) => {
    const normalized = normalizeRepo(repoLink);

    // check cache
    const cached = await findRepoCache(normalized);

    if (cached) {
        return {
            cached: true,
            result: cached.result
        };
    }

    // create job
    const analysis = await createAnalysis(userId, normalized);

    await analysisQueue.add("scan", {
        analysisId: analysis.id,
        repoLink: normalized,
        userType
    });

    return {
        cached: false,
        analysisId: analysis.id
    };
};

export const fetchAnalysisById = async (id) => {
    return await getAnalysisById(id);
};

export const fetchUserAnalyses = async (userId) => {
    return await getAnalysesByUser(userId);
};