import simpleGit from "simple-git";

export const prepareGit = async (repoPath, analysisId) => {
    const git = simpleGit(repoPath);

    // required inside container
    await git.addConfig("user.email", "bot@auto.com");
    await git.addConfig("user.name", "auto-cleaner");

    // 🔴 UNIQUE BRANCH EVERY RUN
    const branch = `cleanup-${analysisId}-${Date.now()}`;

    await git.checkoutLocalBranch(branch);

    return { git, branch };
};

export const commitAndPush = async (git, branch) => {
    await git.add(".");

    const status = await git.status();
    console.log("STATUS:", status);

    if (
        status.files.length === 0 &&
        status.created.length === 0 &&
        status.deleted.length === 0
    ) {
        console.log("No changes to commit");
        return null;
    }

    await git.commit("chore: remove unused files and dependencies");

    // 🔴 NO FORCE PUSH NEEDED ANYMORE
    await git.push("origin", branch);

    return branch;
};