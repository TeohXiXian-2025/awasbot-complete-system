curl -X POST "https://awasbot-bank-checker-611405879605.asia-southeast1.run.app" -H "Authorization: bearer $(gcloud auth print-identity-token)" -H "Content-Type: application/json" -d '{  "account_number": "164829304451" }'
gcloud run deploy awasbot-service   --source .   --region asia-southeast1   --allow-unauthenticated   --memory 2Gi   --timeout 120
gcloud builds log 95fe393b-cb6e-4c59-b9e5-5b2ff98cf1e7 --region asia-southeast1
gcloud run deploy awasbot-service   --source .   --region asia-southeast1   --allow-unauthenticated   --memory 2Gi   --timeout 120
gcloud run deploy awasbot-service --source . --region asia-southeast1 --memory 2Gi
gcloud run services update awasbot-service --timeout=300 --region asia-southeast1
gcloud run deploy awasbot-service --source . --region asia-southeast1 --memory 2Gi --timeout 300
gcloud builds log 95fe393b-cb6e-4c59-b9e5-5b2ff98cf1e7 --region asia-southeast
gcloud auth login
gcloud run deploy awasbot-service   --source .   --region asia-southeast1   --memory 2Gi   --timeout 300
gcloud auth login --no-launch-browser
gcloud config set project awasbot-security
gcloud run deploy awasbot-service   --source .   --region asia-southeast1   --allow-unauthenticated   --memory 2Gi   --timeout 300
gcloud run deploy awasbot-service   --source .   --region asia-southeast1   --allow-unauthenticated   --memory 2Gi   --timeout 300
gcloud run deploy awasbot-service   --source .   --region asia-southeast1   --allow-unauthenticated   --memory 2Gi   --timeout 300
gcloud run deploy awasbot-service \
git init
git add .
ls -d */
mkdir awasbot-project
mv main.py index.html requirements.txt .gitignore awasbot-project/
mv Dockerfile awasbot-project/ 2>/dev/null
mv .env awasbot-project/ 2>/dev/null
cd awasbot-project
echo ".env" > .gitignore
echo "__pycache__/" >> .gitignore
echo "*.png" >> .gitignore
git add .
git commit -m "Initial commit: AwasBot Dual-Bot Ecosystem"
git config --global user.email "25006498@siswa.um.edu.my"
git config --global user.name "Teoh Xi Xian"
git commit -m "Initial commit: AwasBot Dual-Bot Ecosystem"
git branch -M main
git remote add origin https://github.com/TeohXiXian-2025/awasbot-complete-system.git
git push -u origin main
git add
git commit -m "Added threading and real-time database bridge"
git push origin main
git add .
xixianteoh@cloudshell:~ (awasbot-security)git add .
git add .
git rm -rf --cached .gemini
echo ".gemini/" >> .gitignore
git add .
git commit -m "Updated backend threading and real-time frontend bridge"
git push origin main
git pull --rebase origin main
git add .
git commit -m "Final Hackathon Sync"
git push -f origin main
git rm -rf --cached .cache
echo ".cache/" >> .gitignore
git commit --amend -m "Final Hackathon Sync - Fixed Large Files"
git push -f origin main
git reset --soft origin/main
echo ".cache/" >> .gitignore
echo ".gemini/" >> .gitignore
