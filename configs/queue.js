import { Queue } from "bullmq";
import IORedis from "ioredis";

const connection = new IORedis({
    host: process.env.REDIS_HOST || "redis",
    port: process.env.REDIS_PORT || 6379,
    maxRetriesPerRequest: null
});

export const analysisQueue = new Queue("analysis", {
    connection
});