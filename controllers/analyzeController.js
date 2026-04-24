import {
    startAnalysis,
    fetchAnalysisById,
    fetchUserAnalyses
} from "../services/analyzeServices.js";

export const analyzeRepo = async (req, res, next) => {
    try {
        const { repoLink, userType } = req.body;
        const userId = req.user.id;

        if (!repoLink) {
            return res.status(400).json({ error: "repoLink required" });
        }

        const result = await startAnalysis(
            userId,
            repoLink,
            userType
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

export const getAnalysis = async (req, res) => {
    const data = await fetchAnalysisById(req.params.id);
    res.json(data);
};

export const getUserAnalyses = async (req, res) => {
    const data = await fetchUserAnalyses(req.user.id);
    res.json(data);
};