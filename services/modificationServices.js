import fs from "fs";
import path from "path";

export async function applyModifications(repoPath, filtered) {
// DELETE FILES
for (const file of filtered.unusedFiles) {
    const fullPath = path.join(repoPath, file.path);

    try {
    if (fs.existsSync(fullPath)) {
        fs.unlinkSync(fullPath);
        console.log("Deleted file:", fullPath);
    }
    } catch (err) {
    console.error("Failed to delete:", fullPath);
    }
}

// UPDATE package.json
const pkgPath = path.join(repoPath, "package.json");

if (fs.existsSync(pkgPath)) {
    const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf-8"));

    for (const dep of filtered.unusedDeps) {
    if (pkg.dependencies?.[dep.name]) {
        delete pkg.dependencies[dep.name];
        console.log("Removed dep:", dep.name);
    }

    if (pkg.devDependencies?.[dep.name]) {
        delete pkg.devDependencies[dep.name];
        console.log("Removed devDep:", dep.name);
    }
    }

    fs.writeFileSync(pkgPath, JSON.stringify(pkg, null, 2));
}
}