import { Queue } from "bullmq";
import IORedis from "ioredis";

/* 🔴 Use REDIS_URL directly */
const connection = new IORedis(process.env.REDIS_URL, {
    maxRetriesPerRequest: null,

    // required for Redis Cloud (TLS)
    tls: process.env.REDIS_URL.startsWith("rediss://") ? {} : undefined
});

/* export connection for worker */
export { connection };

/* queue for API */
export const analysisQueue = new Queue("analysisQueue", {
    connection
});