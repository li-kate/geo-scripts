#!/bin/bash
#SBATCH --job-name=heat_graphs
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=1
#SBATCH --mem-per-cpu=3G
#SBATCH --time=1:00:00
#SBATCH --output=./logs/heat_pipeline_%j.out
#SBATCH --account=gts-rbasu31
#SBATCH -q inferno
#SBATCH --mail-type=BEGIN,END,FAIL

cd $SLURM_SUBMIT_DIR
mkdir -p logs

module load anaconda3
conda activate base

# ---- CONFIGURE THESE ----
HEAT_DIR="/storage/home/hcoda1/1/kli605/scratch/utci/all_atl"
PBF_DIR="/storage/home/hcoda1/1/kli605/scratch/safe_routes/all_atl/osm"
OUTPUT_DIR="./final/output_osm"
HEAT_COLS="UTCI_07 UTCI_08 UTCI_09 UTCI_10 UTCI_11 UTCI_12 UTCI_13 UTCI_14 UTCI_15 UTCI_16 UTCI_17 UTCI_18 UTCI_19 UTCI_20 NDVI"

mkdir -p "$OUTPUT_DIR"

# ---- DEFINE JOBS: each line is HEAT_FILE PBF_FILE OUTPUT_FILE ----
# Add/remove lines as needed. Paths can be absolute or relative to HEAT_DIR/PBF_DIR.
JOBS=(
    "Atlanta-062226_UTCI_final.geojson Atlanta_062226.osm.pbf Atlanta_062226_UTCI_final.osm"
)

# ---- RUN ----
TOTAL=${#JOBS[@]}
SUCCESS=0
FAILED=0

for job in "${JOBS[@]}"; do
    # Split the line into three fields
    read -r HEAT PBF OUT <<< "$job"

    echo ""
    echo "============================================================"
    echo "Processing: $HEAT"
    echo "============================================================"

    python -u matching.py \
        --heat-path "${HEAT_DIR}/${HEAT}" \
        --pbf-path "${PBF_DIR}/${PBF}" \
        --output-path "${OUTPUT_DIR}/${OUT}" \
        --heat-cols $HEAT_COLS \
        --keep-unmatched
        

    if [ $? -eq 0 ]; then
        ((SUCCESS++))
    else
        echo "FAILED: $HEAT"
        ((FAILED++))
    fi
done

echo ""
echo "============================================================"
echo "BATCH COMPLETE: $SUCCESS/$TOTAL succeeded, $FAILED failed"
echo "============================================================"