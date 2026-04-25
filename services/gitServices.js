import { execSync } from "child_process";
import axios from "axios";

// create branch + commit + push
export function createBranchAndPush(repoPath, jobId, token, repoUrl) {
const branch = `auto-cleanup-${jobId}`;

// inject token into remote URL
const authedUrl = repoUrl.replace(
    "https://",
    `https://${token}@`
);

execSync(`git remote set-url origin ${authedUrl}`, { cwd: repoPath });

execSync(`git checkout -b ${branch}`, { cwd: repoPath });
execSync(`git add .`, { cwd: repoPath });

try {
    execSync(`git commit -m "auto cleanup unused code"`, {
    cwd: repoPath
    });
} catch {
    console.log("Nothing to commit");
}

execSync(`git push origin ${branch}`, { cwd: repoPath });

return branch;
}

// parse repo URL
export function parseRepo(repoUrl) {
const parts = repoUrl.split("/");
return {
    owner: parts[3],
    repo: parts[4].replace(".git", "")
};
}

// create PR
export async function createPR({ owner, repo, branch, token }) {
const res = await axios.post(
    `https://api.github.com/repos/${owner}/${repo}/pulls`,
    {
    title: "Auto cleanup unused code",
    head: branch,
    base: "main"
    },
    {
    headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json"
    }
    }
);

return res.data.html_url;
}