import {
    startAnalysis,
    fetchAnalysisById,
    fetchUserAnalyses,
    enqueueApplyJob
} from "../services/analyzeServices.js";

/* ================= START ================= */
export const analyzeRepo = async (req, res, next) => {
    try {
        const { repoLink, userType } = req.body;
        const userId = req.user.id;

        if (!repoLink) {
            return res.status(400).json({ error: "repoLink required" });
        }

        const result = await startAnalysis(userId, repoLink, userType);

        if (result.cached) {
            return res.json(result);
        }

        res.status(202).json(result);

    } catch (err) {
        next(err);
    }
};

/* ================= GET ONE ================= */
export const getAnalysis = async (req, res, next) => {
    try {
        const analysisId = Number(req.params.id);
        const userId = req.user.id;

        const data = await fetchAnalysisById(analysisId, userId);

        if (!data) {
            return res.status(404).json({ error: "Analysis not found" });
        }

        res.json(data);

    } catch (err) {
        next(err);
    }
};

/* ================= GET USER ================= */
export const getUserAnalyses = async (req, res, next) => {
    try {
        const data = await fetchUserAnalyses(req.user.id);
        res.json(data);
    } catch (err) {
        next(err);
    }
};

/* ================= APPLY ================= */
export const applyChanges = async (req, res, next) => {
    try {
        const analysisId = Number(req.params.id);
        const userId = req.user.id;

        const analysis = await fetchAnalysisById(analysisId, userId);

        if (!analysis) {
            return res.status(404).json({ error: "Not found" });
        }

        await enqueueApplyJob({
            analysisId,
            userId,
            files: req.body.files || [],
            deps: req.body.deps || []
        });

        res.json({ message: "Apply queued" });

    } catch (err) {
        next(err);
    }
};