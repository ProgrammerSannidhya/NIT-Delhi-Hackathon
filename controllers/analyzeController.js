import {
startAnalysis,
fetchAnalysisById,
fetchUserAnalyses,
enqueueApplyJob
} from "../services/analyzeServices.js";

// POST /analyze
export const analyzeRepo = async (req, res, next) => {
try {
const { repoLink, userType, mode = "report" } = req.body;
const userId = req.user.id;

    if (!repoLink) {
        return res.status(400).json({ error: "repoLink required" });
    }

    const result = await startAnalysis(
        userId,
        repoLink,
        userType,
        mode
    );

    if (result.cached) {
        return res.json({
            message: "Returned from cache",
            data: result.result
        });
    }

    return res.status(202).json({
        message: "Analysis queued",
        analysisId: result.analysisId
    });

} catch (err) {
    next(err);
}

};

// GET /analyze/
export const getAnalysis = async (req, res, next) => {
try {
const analysisId = req.params.id;
const userId = req.user.id;

    const data = await fetchAnalysisById(analysisId);

    // 🔴 THIS is why you're getting nothing
    if (!data) {
        return res.status(404).json({
            error: "Analysis not found or not processed yet"
        });
    }

    // security check
    if (data.user_id !== userId) {
        return res.status(403).json({
            error: "Forbidden"
        });
    }

    res.json({
        id: data.id,
        repo_url: data.repo_url,
        status: data.status,
        raw: data.result,
        classified: data.filtered_result,
        pr_url: data.pr_url,
        created_at: data.created_at
    });

} catch (err) {
    next(err);
}

};

// GET /analyze/user/me
export const getUserAnalyses = async (req, res, next) => {
try {
const userId = req.user.id;

    const data = await fetchUserAnalyses(userId);

    const formatted = data.map(a => ({
        id: a.id,
        repo_url: a.repo_url,
        status: a.status,
        pr_url: a.pr_url,
        created_at: a.created_at
    }));

    res.json({
        count: formatted.length,
        analyses: formatted
    });

} catch (err) {
    next(err);
}

};

// POST /analyze//apply
export const applyChanges = async (req, res, next) => {
try {
const analysisId = req.params.id;
const userId = req.user.id;
const { files = [], deps = [] } = req.body;

    const analysis = await fetchAnalysisById(analysisId);

    if (!analysis) {
        return res.status(404).json({ error: "Not found" });
    }

    if (analysis.user_id !== userId) {
        return res.status(403).json({ error: "Forbidden" });
    }

    if (analysis.status !== "waiting_for_user") {
        return res.status(400).json({
            error: "Analysis not ready for apply"
        });
    }

    await enqueueApplyJob({
        analysisId,
        userId,
        files,
        deps
    });

    res.json({
        message: "Apply job queued"
    });

} catch (err) {
    next(err);
}

};