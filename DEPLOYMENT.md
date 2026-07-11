# Deployment Guide (AWS Free Tier)

This guide provides step-by-step instructions for deploying the Mask Guard demo project (both frontend and backend with Ollama) using a git URL on AWS for **free** using the AWS Free Tier.

> **Note**: Running large AI models like Llama 3 locally via Ollama requires significant memory. The AWS Free Tier provides `t2.micro` or `t3.micro` instances with 1GB of RAM. Running Ollama on these instances will be extremely slow and might crash due to out-of-memory (OOM) errors. For a proper production environment, a more powerful instance (like `t3.medium` or higher) is recommended, but for a zero-cost demo, you can attempt it using swap space.

## Prerequisites
- An AWS Account (eligible for Free Tier).
- Your code hosted on a Git repository (e.g., GitHub, GitLab).

---

## Step 1: Launch an EC2 Instance (Backend & Frontend)

1. Log in to the [AWS Management Console](https://console.aws.amazon.com/).
2. Go to **EC2** -> **Launch Instance**.
3. **Name**: `mask-guard-demo`.
4. **AMI**: Select **Ubuntu Server 22.04 LTS** (Free tier eligible).
5. **Instance Type**: `t2.micro` or `t3.micro` (Free tier eligible).
6. **Key Pair**: Create a new key pair (e.g., `mask-guard-key.pem`), download it, and keep it safe.
7. **Network Settings**:
   - Allow SSH traffic from Anywhere (or your IP).
   - Allow HTTP traffic from the internet.
   - Allow HTTPS traffic from the internet.
8. **Storage**: Set to 30 GB (Maximum free tier eligible).
9. Click **Launch Instance**.

## Step 2: Configure Security Groups

1. Go to **EC2 Dashboard** -> **Instances**, select your instance.
2. Click the **Security** tab and click on the associated Security Group.
3. Edit **Inbound Rules** and add:
   - **Custom TCP** | Port `5000` | Source `0.0.0.0/0` (For Flask Backend)
   - **Custom TCP** | Port `5173` | Source `0.0.0.0/0` (For React Frontend, optional if using a reverse proxy)

## Step 3: Connect to Your Instance and Setup Swap Space

Since 1GB RAM is not enough for Ollama, we need to create a swap file.

```bash
# Connect to your instance via SSH
ssh -i "mask-guard-key.pem" ubuntu@<YOUR_EC2_PUBLIC_IP>

# Create a 4GB Swap file
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Make swap permanent
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## Step 4: Install Dependencies

```bash
# Update packages
sudo apt update && sudo apt upgrade -y

# Install Python, pip, and Node.js
sudo apt install python3-pip python3-venv npm git -y

# Install Node.js v18 (recommended for Vite/React)
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs
```

## Step 5: Install Ollama

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull the llama3 model (This will take time and max out the CPU/Disk)
ollama pull llama3
```

## Step 6: Clone Your Repository

```bash
# Clone the repository
git clone <YOUR_GIT_REPOSITORY_URL>
cd mask-guard
```

## Step 7: Setup and Run the Backend (Flask)

```bash
cd mask-guard-be-flask

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install -r requirements.txt

# Run the Flask app in the background using nohup or screen
# The app binds to 0.0.0.0 to be accessible publicly
nohup flask run --host=0.0.0.0 --port=5000 > backend.log 2>&1 &
```

## Step 8: Setup and Run the Frontend (React/Vite)

```bash
cd ../mask-guard-fe-react

# Install Node dependencies
npm install

# Modify your frontend configuration to point to the EC2 Public IP instead of localhost
# E.g. in your .env or API config: VITE_API_BASE_URL=http://<YOUR_EC2_PUBLIC_IP>:5000

# Build and preview, or run the dev server exposing the host
nohup npm run dev -- --host 0.0.0.0 --port 5173 > frontend.log 2>&1 &
```

## Step 9: Access Your Application

- **Frontend**: `http://<YOUR_EC2_PUBLIC_IP>:5173`
- **Backend API**: `http://<YOUR_EC2_PUBLIC_IP>:5000`

### Important Considerations for Free Tier
- **Performance**: Expect responses from Ollama to be extremely slow (multiple minutes per request) on a `t2.micro` instance because it will rely entirely on disk swap instead of RAM.
- **Billing**: AWS Free Tier covers 750 hours of `t2.micro` usage per month. Make sure you don't run multiple instances.
- **Security**: Exposing ports 5000 and 5173 directly isn't recommended for production. For a real deployment, consider using Nginx as a reverse proxy.
