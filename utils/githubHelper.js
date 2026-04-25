import axios from "axios";

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

export const forkRepo = async (repoUrl) => {
    const token = process.env.GITHUB_TOKEN;

    if (!token) {
        throw new Error("GITHUB_TOKEN missing");
    }

    const parts = repoUrl.split("/");
    const owner = parts[3];
    const repo = parts[4].replace(".git", "");

    const res = await axios.post(
        `https://api.github.com/repos/${owner}/${repo}/forks`,
        {},
        {
            headers: {
                Authorization: `Bearer ${token}`,
                Accept: "application/vnd.github+json"
            }
        }
    );

    const forkUrl = res.data.clone_url;

    // GitHub fork is not instantly ready
    await sleep(2000);

    return forkUrl;
};

export const createPullRequest = async ({
    repoUrl,
    branch,
    analysisId
}) => {
    const token = process.env.GITHUB_TOKEN;
    const username = process.env.GITHUB_USERNAME;

    const parts = repoUrl.split("/");
    const owner = parts[3];
    const repo = parts[4].replace(".git", "");

    const res = await axios.post(
        `https://api.github.com/repos/${owner}/${repo}/pulls`,
        {
            title: `Cleanup unused code (#${analysisId})`,
            head: `${username}:${branch}`, // 🔴 IMPORTANT
            base: "main",
            body: "Automated cleanup"
        },
        {
            headers: {
                Authorization: `Bearer ${token}`,
                Accept: "application/vnd.github+json"
            }
        }
    );

    return res.data.html_url;
};