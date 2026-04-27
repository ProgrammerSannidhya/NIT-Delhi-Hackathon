import {
createAnalysis,
getAnalysisById,
getAnalysesByUser,
updateAnalysis
} from "../models/analyzeModel.js";

import { findRepoCache } from "../models/repoCacheModel.js";
import { analysisQueue } from "../configs/queue.js";
import axios from "axios";

/* ================= HELPERS ================= */
const normalizeRepo = (url) =>
url.trim().toLowerCase().replace(/.git$/, "").replace(/\/$/, "");

const getLatestCommitSha = async (repoUrl, branch = "main") => {
const parts = repoUrl.split("/");
const owner = parts[3];
const repo = parts[4].replace(".git", "");


const res = await axios.get(
    `https://api.github.com/repos/${owner}/${repo}/commits/${branch}`
);

return res.data.sha;


};

/* ================= START ANALYSIS ================= */
export const startAnalysis = async (
userId,
repoLink,
userType,
mode = "report"
) => {
const normalized = normalizeRepo(repoLink);
const branch = "main";

const commitSha = await getLatestCommitSha(normalized, branch);

const cached = await findRepoCache(normalized, branch, commitSha);
if (cached) {
    return { cached: true, result: cached.result };
}

const analysis = await createAnalysis(userId, normalized);

await analysisQueue.add("scan", {
    analysisId: analysis.id,
    repoLink: normalized,
    userType,
    branch,
    commitSha,
    mode
});

return { cached: false, analysisId: analysis.id };

};

/* ================= FETCH ================= */
export const fetchAnalysisById = async (id, userId) => {
const data = await getAnalysisById(id, userId);
if (!data) return null;

return {
    ...data,
    result: data.result || null,
    filtered_result: data.filtered_result || null,
    status: data.status || "queued"
};

};

export const fetchUserAnalyses = async (userId) => {
return getAnalysesByUser(userId);
};

/* ================= APPLY ================= */
export const enqueueApplyJob = async ({
analysisId,
userId,
files = [],
deps = []
}) => {
const analysis = await getAnalysisById(analysisId, userId);
if (!analysis) throw new Error("Analysis not found");

if (analysis.status !== "waiting_for_user") {
    throw new Error("Analysis not ready for apply");
}

await updateAnalysis(analysisId, {
    status: "applying_changes"
});

await analysisQueue.add("apply", {
    analysisId,
    userId,
    files,
    deps
});

};
