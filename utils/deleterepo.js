// utils/deleterepo.js

import fs from "fs";
import path from "path";
import { getReposBaseDir } from "./clonerepo.js";

const BASE_DIR = getReposBaseDir();

export  function deleteRepo(repoPath) {
    if (!repoPath) {
        console.warn("deleteRepo called with empty path");
        return;
    }

    const resolved = path.resolve(repoPath);

    console.log("DELETE REQUEST:", resolved);

    // Guard 1: must be inside BASE_DIR (strict)
    const base = BASE_DIR.endsWith(path.sep) ? BASE_DIR : BASE_DIR + path.sep;
    if (!resolved.startsWith(base)) {
        throw new Error("Blocked unsafe delete (outside repos): " + resolved);
    }

    // Guard 2: never delete base itself
    if (resolved === BASE_DIR) {
        throw new Error("Refusing to delete base repos directory");
    }

    // Guard 3: must exist and be a directory
    if (!fs.existsSync(resolved)) {
        console.warn("Delete skipped (not found):", resolved);
        return;
    }

    const stat = fs.statSync(resolved);
    if (!stat.isDirectory()) {
        throw new Error("Refusing to delete non-directory: " + resolved);
    }

    // DELETE
    fs.rmSync(resolved, { recursive: true, force: true });

    console.log("DELETED:", resolved);
}