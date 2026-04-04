import express from 'express'

import cloneRepo from './utils/clonerepo.js';

import deleteRepo from './utils/deleterepo.js';

import { runScanner } from './utils/runscan..js';

const app = express();

app.use(express.json());

app.get("/",(req,res)=>{
    res.json("Server is running !");
})

let repoPath;

app.post("/analyze",async(req,res)=>{
    try {
    const {repoLink} = req.body;

    console.log(repoLink);

    repoPath = await cloneRepo(repoLink);

    console.log('Cloned!')


    const output = await runScanner(repoPath);

    if(output.error){
        return res.status(500).json({
            error : output.error
        })
    }
    return res.status(200).json({
    repoType: output.repoType,

    unusedFiles: output.unusedFiles,
    unusedExports: output.unusedExports,
    unusedDeps: output.unusedDeps,

    summary: output.summary,

    scores: output.scores
    });
        } catch (error) {
            console.error('error in analysis : ',error);
            res.json({
                message : "something went wrong !!",
                error : error
            })
        }finally{
            deleteRepo(repoPath);
        } 
    })

const port = 3000;

app.listen(port,(req,res)=>{
    console.log('server is running on Port : ',port );
})