import simpleGit from "simple-git";
import path from "path";
import fs from "fs";

const BASE_DIR = path.resolve("repos");

export const getReposBaseDir = () => BASE_DIR;

export async function cloneRepo(repoUrl) {
if (!repoUrl || typeof repoUrl !== "string") {
throw new Error("Invalid repo URL");
}

if (!fs.existsSync(BASE_DIR)) {
    fs.mkdirSync(BASE_DIR, { recursive: true });
}

const repoName = repoUrl
    .split("/")
    .pop()
    .replace(".git", "");

const target = path.join(BASE_DIR, `${repoName}_${Date.now()}`);

console.log("CLONING INTO:", target);

await simpleGit().clone(repoUrl, target, ["--depth", "1"]);

return target;


}