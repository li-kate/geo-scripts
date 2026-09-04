# geo-scripts
Collection of tools useful for processing geospatial files for various purposes.

# How to Run `.sh` Files

## 1. Clone or Download the Repository

Clone the Git repository to PACE, or download the scripts and place them on PACE.

## 2. Make the Script Executable

From the directory containing the script:

```bash
chmod +x extract_network.sh
```

## 3. Make Sure Environment is Created and Up (if needed)
```
module load anaconda3
conda create -n osmium_env -c conda-forge osmium-tool
conda install -n osmium_env -c conda-forge gdal
conda activate osmium_env
```

## 4. Run the Script

```bash
./extract_network.sh
```