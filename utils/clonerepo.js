import { simpleGit, CleanOptions } from 'simple-git';

import path from 'path'

import { fileURLToPath } from 'url';
import fs  from 'fs'

// recreate __dirname
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

simpleGit().clean(CleanOptions.FORCE);

const cloneRepo =async(repoLink)=>{

    try {
    console.log(repoLink);
    const repoName = repoLink.split('/').pop().replace('.git', '');


    const git = simpleGit();

    
    const baseDir =  path.join(__dirname,'repos');
    
    if(!fs.existsSync(baseDir)){
        fs.mkdirSync(baseDir);
    }   

    const target  = path.join(baseDir,`${repoName}_${Date.now()}`);

    await git.clone(repoLink,target,["--depth", "1"]);
    
    console.log('Cloned Repo : ',repoName);
    return target;
    } catch (error) {
        console.log('error from clone repo ' ,error);  
        throw error;
    }
}

export default cloneRepo;