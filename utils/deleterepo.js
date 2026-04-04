import fs, { existsSync } from 'fs'

const deleteRepo = (repoPath)=>{
    try {
        if(repoPath && existsSync(repoPath)){
            fs.rmdirSync(repoPath ,{
                recursive: true, 
                force: true
                });
        }
    } catch (error) {

        console.log('deleted : '+repoPath);

    }
}

export default deleteRepo;