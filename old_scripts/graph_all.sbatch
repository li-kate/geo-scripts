#!/bin/bash
#SBATCH --job-name=heat_graphs
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --mem-per-cpu=32G
#SBATCH --time=12:00:00
#SBATCH --output=./logs/heat_pipeline_%j.out
#SBATCH --account=gts-rbasu31
#SBATCH -q inferno
#SBATCH --mail-type=BEGIN,END,FAIL

cd $SLURM_SUBMIT_DIR
mkdir -p logs

module load anaconda3
conda activate base

# ---- CONFIGURE THESE ----
HEAT_DIR="/storage/home/hcoda1/1/kli605/scratch/utci"
PBF_DIR="/storage/home/hcoda1/1/kli605/scratch/final"
OUTPUT_DIR="./final/output_osm"
HEAT_COLS="UTCI_07 UTCI_08 UTCI_09 UTCI_10 UTCI_11 UTCI_12 UTCI_13 UTCI_14 UTCI_15 UTCI_16 UTCI_17 UTCI_18 UTCI_19 UTCI_20 NDVI"

mkdir -p "$OUTPUT_DIR"

# ---- DEFINE JOBS: each line is HEAT_FILE PBF_FILE OUTPUT_FILE ----
# Add/remove lines as needed. Paths can be absolute or relative to HEAT_DIR/PBF_DIR.
JOBS=(
    "Boston.geojson          boston-260503-filtered.osm.pbf          Boston-260503-UTCI.osm"
    "Atlanta.geojson         atlanta-260503-filtered.osm.pbf         Atlanta-260503-UTCI.osm"
    "Dallas.geojson          dallas-260503-filtered.osm.pbf          Dallas-260503-UTCI.osm"
    "Houston.geojson         houston-260511-filtered.osm.pbf         Houston-260511-UTCI.osm"
    "Losangeles.geojson     losangeles-260503-filtered.osm.pbf      Los_Angeles-260503-UTCI.osm"
    "Miami.geojson           miami-260503-filtered.osm.pbf           Miami-260503-UTCI.osm"
    "NYC.geojson             nyc-260503-filtered.osm.pbf             NYC-260503-UTCI.osm"
    "Philadelphia.geojson    philadelphia-260503-filtered.osm.pbf    Philadelphia-260503-UTCI.osm"
    "Seattle.geojson         seattle-051426-filtered.osm.pbf         Seattle-260514-UTCI.osm"
    "SF.geojson              sf-260503-filtered.osm.pbf              SF-260503-UTCI.osm"
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
        --bbox-buffer-km 2.0

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
