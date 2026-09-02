#!/bin/bash
#SBATCH --job-name=heat_graphs
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --mem-per-cpu=64G
#SBATCH --time=12:00:00
#SBATCH --output=./logs/heat_pipeline_%j.out
#SBATCH --account=gts-rbasu31
#SBATCH -q inferno
#SBATCH --mail-type=BEGIN,END,FAIL

set -euo pipefail

echo "=========================================="
echo "OSM extraction job"
echo "Job ID: $SLURM_JOB_ID"
echo "Node:   $SLURMD_NODENAME"
echo "Start:  $(date)"
echo "=========================================="

# --------------------------------------------------
# 1. Load Anaconda
# --------------------------------------------------

module load anaconda3

# Make conda available to this non-interactive shell
source "$(conda info --base)/etc/profile.d/conda.sh"

# --------------------------------------------------
# 2. Check that the required files exist
# --------------------------------------------------

if [[ ! -f "extract_network.sh" ]]; then
    echo "ERROR: extract_network.sh not found."
    exit 1
fi

if [[ ! -f "answers.txt" ]]; then
    echo "ERROR: answers.txt not found."
    exit 1
fi

# --------------------------------------------------
# 3. Run the existing interactive script
#    using answers.txt as stdin
# --------------------------------------------------

echo
echo "Running extract_network.sh with answers.txt..."
echo

bash extract_network.sh < answers.txt

# --------------------------------------------------
# 4. Done
# --------------------------------------------------

echo
echo "=========================================="
echo "OSM extraction job finished"
echo "End: $(date)"
echo "=========================================="