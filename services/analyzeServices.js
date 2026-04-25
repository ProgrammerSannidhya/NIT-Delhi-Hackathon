import {
createAnalysis,
getAnalysisById,
getAnalysesByUser,
updateAnalysis
} from "../models/analyzeModel.js";

import {
findRepoCache,
upsertRepoCache
} from "../models/repoCacheModel.js";

import { analysisQueue } from "../configs/queue.js";
import axios from "axios";

// normalize repo URL
const normalizeRepo = (url) =>
url
.trim()
.toLowerCase()
.replace(/.git$/, "")
.replace(/\/$/, "");

// get latest commit SHA
const getLatestCommitSha = async (repoUrl, branch = "main") => {
const parts = repoUrl.split("/");
const owner = parts[3];
const repo = parts[4].replace(".git", "");


const res = await axios.get(
    `https://api.github.com/repos/${owner}/${repo}/commits/${branch}`
);

return res.data.sha;


};

// start analysis
export const startAnalysis = async (
userId,
repoLink,
userType,
mode = "report"
) => {
const normalized = normalizeRepo(repoLink);
const branch = "main";


const commitSha = await getLatestCommitSha(normalized, branch);

const cached = await findRepoCache(
    normalized,
    branch,
    commitSha
);

if (cached) {
    return {
        cached: true,
        result: cached.result
    };
}

const analysis = await createAnalysis(
    userId,
    normalized,
    "queued"
);

await analysisQueue.add("scan", {
    analysisId: analysis.id,
    repoLink: normalized,
    userType,
    branch,
    commitSha,
    mode
});

return {
    cached: false,
    analysisId: analysis.id
};


};

// fetch single
export const fetchAnalysisById = async (id) => {
const data = await getAnalysisById(id);

if (!data) return null;

return {
    ...data,
    result: data.result || null,
    filtered_result: data.filtered_result || null,
    status: data.status || "queued"
};


};

// fetch all user analyses
export const fetchUserAnalyses = async (userId) => {
return await getAnalysesByUser(userId);
};

// enqueue apply job
export const enqueueApplyJob = async ({
analysisId,
userId,
files,
deps
}) => {
await updateAnalysis(analysisId, {
status: "applying"
});


await analysisQueue.add("apply", {
    analysisId,
    userId,
    files,
    deps
});

};
