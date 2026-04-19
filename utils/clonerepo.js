// utils/clonerepo.js

import simpleGit from "simple-git";
import path from "path";
import fs from "fs";

// absolute base, outside utils
const BASE_DIR = path.resolve("repos");

export const getReposBaseDir = () => BASE_DIR;

export default async function cloneRepo(repoUrl) {
    if (!repoUrl || typeof repoUrl !== "string") {
        throw new Error("Invalid repo URL");
    }

    if (!fs.existsSync(BASE_DIR)) {
        fs.mkdirSync(BASE_DIR, { recursive: true });
    }

    const repoName = repoUrl.split("/").pop().replace(".git", "");
    const target = path.join(BASE_DIR, `${repoName}_${Date.now()}`);

    console.log("CLONING INTO:", target);

    await simpleGit().clone(repoUrl, target, ["--depth", "1"]);

    return target; // ALWAYS absolute path inside BASE_DIR
}