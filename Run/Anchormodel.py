import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.svm import SVR
from sklearn.multioutput import MultiOutputRegressor
from sklearn.metrics import mean_squared_error, mean_absolute_error
from math import sqrt
import time

# --- 1. CONFIGURATION ---

# The anchors whose metrics are READ as INPUT for the model (All 5 anchors are used as features)
INPUT_ANCHORS_LIVE = [1, 2, 3, 4, 5] 
INPUT_ANCHOR_COUNT = len(INPUT_ANCHORS_LIVE) # 5

# The anchors whose ranges are PREDICTED as OUTPUT (Now all 5 are targeted for prediction)
OUTPUT_ANCHORS = [1, 2, 3, 4, 5]
OUTPUT_ANCHOR_COUNT = len(OUTPUT_ANCHORS) # 5

# Define the 6 specific UWB quality metrics to be used as input features (X)
FEATURE_TYPES = ['m', 'peak', 'pwr', 'fp_idx', 'acc', 'xo'] 
FEATURES_PER_ANCHOR = len(FEATURE_TYPES) # 6
TOTAL_INPUT_FEATURES = INPUT_ANCHOR_COUNT * FEATURES_PER_ANCHOR # 5 * 6 = 30

# Define the anchor coordinates (MANDATORY for multilateration/localization)
# Must contain coordinates for all 5 OUTPUT_ANCHORS (A1 through A5).
# Using placeholder values based on common UWB setups.
ANCHOR_COORDINATES = np.array([
    [0, 0.0, 0],# Anchor 1
    [4, 4, 0],  # Anchor 2
    [0, 4, 2],  # Anchor 3
    [4, 0, 2], # Anchor 4
    [4, 0, 0]  # Anchor 5
])


# The output (Y) is the true range for all 5 anchors.
TRUE_RANGE_OUTPUTS = [f'r{i}_true' for i in OUTPUT_ANCHORS] # 5 outputs

# List of input columns the script expects from the CSV, 
# following the aX_ftype naming convention, for ALL 5 anchors.
INPUT_COLUMNS_TO_EXTRACT = [
    f'a{i}_{ftype}' 
    for i in INPUT_ANCHORS_LIVE 
    for ftype in FEATURE_TYPES
]

# --- 2. DATA LOADING FUNCTION ---

def load_dataset(filepath=None, true_range=None):
    """
    Loads the dataset from a specified CSV file (containing 30 features for A1-A5)
    and generates the target values (Y) based on the provided true_range for ALL 5 anchors.
    """
    if not filepath:
        print("ERROR: No data file path specified.")
        return np.array([]), np.array([])
    
    if true_range is None:
        raise ValueError("The 'true_range' (in meters) must be specified for this dataset.")
    
    print(f"Attempting to load features from: '{filepath}' (True Range = {true_range:.1f} m)")
    
    try:
        df = pd.read_csv(filepath)
        
        # Check if all required input columns exist in the DataFrame
        missing_input_cols = [col for col in INPUT_COLUMNS_TO_EXTRACT if col not in df.columns]

        if missing_input_cols:
             raise ValueError(f"Missing required input features in CSV: {missing_input_cols}. Ensure header format is correct (e.g., 'a1_m') and includes all anchors {INPUT_ANCHORS_LIVE}.")
        
        # --- FIX FOR NaN ERROR ---
        initial_count = len(df)
        
        # Select only the columns we intend to use
        df_selected = df[INPUT_COLUMNS_TO_EXTRACT]
        
        # Drop rows where ANY of the selected input features is NaN
        df_cleaned = df_selected.dropna()
        
        cleaned_count = len(df_cleaned)
        dropped_count = initial_count - cleaned_count
        
        if dropped_count > 0:
            print(f"INFO: Dropped {dropped_count} samples containing NaN values.")
        
        # Extract features (X) from the cleaned DataFrame
        X = df_cleaned.values 
        
        # Generate Y targets: all 5 true ranges are equal to the known distance
        Y = np.full((cleaned_count, OUTPUT_ANCHOR_COUNT), true_range)
        
        if X.size == 0:
            print("WARNING: No valid samples remain after dropping NaN values.")
            return np.array([]), np.array([])
        
        print(f"Successfully loaded {len(X)} data samples.")
        print(f"Using {X.shape[1]} input features (6 types for {INPUT_ANCHOR_COUNT} anchors) to predict {Y.shape[1]} true ranges (all {true_range:.1f}m).")
        return X, Y
    
    except FileNotFoundError:
        print(f"ERROR: File not found at '{filepath}'. Please check the path and ensure the file is in the correct location.")
        return np.array([]), np.array([])
    except Exception as e:
        print(f"An error occurred while loading data: {e}")
        return np.array([]), np.array([])

# --- 3. CORE LOCALIZATION FUNCTIONS ---

def multilaterate_3d(anchor_coords, corrected_ranges):
    """
    Calculates the 3D position of the tag using Nonlinear Least Squares (NLS) 
    based on the corrected ranges from the anchors.
    
    Args:
        anchor_coords (np.array): Nx3 array of anchor coordinates (x, y, z).
        corrected_ranges (np.array): N array of corrected distances to the tag.
        
    Returns:
        np.array: (x, y, z) predicted tag location, or None if unsolvable.
    """
    
    # ----------------------------------------------------------------------
    # Simplified NLS approximation (based on linearizing the range equations):
    # This method is robust with 4 or more equations (5 ranges in this case).
    # ----------------------------------------------------------------------
    
    N = len(anchor_coords)
    if N < 4:
        # A minimum of 4 anchors is highly recommended for stable 3D localization.
        print("WARNING: Multilateration may be highly unstable or fail if N < 4.")
        if N < 3: 
            return np.array([np.nan, np.nan, np.nan]) 

    A = []
    b = []
    
    # Use the last anchor (A_N-1) as the reference point for linearization
    ref_idx = N - 1
    ref_x, ref_y, ref_z = anchor_coords[ref_idx]
    ref_r = corrected_ranges[ref_idx]

    for i in range(N):
        if i == ref_idx:
            continue
            
        xi, yi, zi = anchor_coords[i]
        ri = corrected_ranges[i]
        
        # Matrix A (based on 2 * (xi - x_ref))
        A.append([
            2 * (ref_x - xi),
            2 * (ref_y - yi),
            2 * (ref_z - zi)
        ])
        
        # Vector b (based on ref_r^2 - ri^2 - ref_coord_sum + coord_sum)
        b.append(
            (ri**2 - ref_r**2) - 
            (xi**2 + yi**2 + zi**2) + 
            (ref_x**2 + ref_y**2 + ref_z**2)
        )

    A = np.array(A)
    b = np.array(b)

    # Solve the linear system Ax = b using Least Squares
    try:
        # np.linalg.lstsq is used because N > 3, making the system overdetermined (robust)
        predicted_pos, residuals, rank, singular_values = np.linalg.lstsq(A, b, rcond=None)
        return predicted_pos
    except np.linalg.LinAlgError:
        print("Multilateration Failed: Singular matrix error.")
        return np.array([np.nan, np.nan, np.nan])


def train_and_evaluate_svr(X, Y):
    """Trains the SVR model to predict 5 corrected ranges and evaluates its performance."""
    
    # 1. Split data into training and testing sets
    X_train, X_test, Y_train, Y_test = train_test_split(
        X, Y, test_size=0.2, random_state=42
    )
    print(f"Training set size: {len(X_train)} samples")
    print(f"Test set size: {len(X_test)} samples")
    print("\nStarting SVR training...")
    
    start_time = time.time()

    # 2. Define the SVR model
    # Model input: 30 features (5 anchors * 6 metrics)
    # Model output: 5 ranges (A1 through A5)
    base_svr = SVR(kernel='rbf', C=100, epsilon=0.1)
    model = MultiOutputRegressor(base_svr)

    # 3. Train the model
    model.fit(X_train, Y_train)
    
    end_time = time.time()
    print(f"Training complete in {end_time - start_time:.2f} seconds.")

    # 4. Make predictions on the test set
    Y_pred_ranges = model.predict(X_test)

    # 5. Evaluate performance (Range Prediction)
    mae_error = mean_absolute_error(Y_test, Y_pred_ranges)
    rmse_error = sqrt(mean_squared_error(Y_test, Y_pred_ranges))
    
    print("\n--- Model Evaluation (Test Set - Range Prediction) ---")
    print(f"MEAN ABSOLUTE ERROR (MAE): {mae_error:.4f} m (cm: {mae_error*100:.2f})")
    print(f"ROOT MEAN SQUARED ERROR (RMSE): {rmse_error:.4f} m (cm: {rmse_error*100:.2f})")
    print("------------------------------------------------------")
    
    # Display individual anchor MAE for debugging/comparison
    individual_mae = np.mean(np.abs(Y_test - Y_pred_ranges), axis=0)
    for i in range(OUTPUT_ANCHOR_COUNT):
        anchor_id = OUTPUT_ANCHORS[i]
        

    # 6. Full Localization Demonstration (Range Correction + Multilateration)
    print("\n--- Full 3D Localization Demonstration ---")

    # Use a sample from the test set
    sample_input = X_test[0]
    sample_truth_range = Y_test[0]

    # Step A: Predict Corrected Ranges using the SVR model
    # Input is 30 features (5 anchors * 6 metrics)
    corrected_ranges = model.predict(sample_input.reshape(1, -1))[0] # Output is 5 ranges (A1-A5)
    
    # Step B: Multilaterate using the corrected ranges
    predicted_3d_pos = multilaterate_3d(ANCHOR_COORDINATES, corrected_ranges)
    
    # We will only show the predicted 3D position, as there is no ground truth (x,y,z) available.
    print(f"Input Features (30 total): {sample_input[:3].round(0)}...{sample_input[-3:].round(0)} (Metrics for A1-A5)")
    print("-" * 75)
    print(f"SVR Predicted Ranges (r1-r5):   {corrected_ranges.round(4)}")
    print(f"Multilateration Predicted 3D Pos: {predicted_3d_pos.round(4)} m")
    
    # --- Prediction Usage Note ---
    print(f"\n[LIVE USAGE NOTE]: For a live measurement, you must extract the {TOTAL_INPUT_FEATURES} quality metrics from the UWB output (a1_m...a5_xo) and pass them as a single {TOTAL_INPUT_FEATURES}-element NumPy array into the trained SVR model to get the corrected ranges for all 5 anchors.")
    
    # *** REQUIRED FORMAT FOR LIVE INPUT (30-element array) ***
    
    # Define the sequence of features clearly
    feature_sequence = [f'a{i}_{ftype}' for i in INPUT_ANCHORS_LIVE for ftype in FEATURE_TYPES]
    print(f"\n[EXACT INPUT FORMAT - ORDER MATTERS]:")
    print(f"np.array([ {', '.join(feature_sequence)} ])")
    
    return model

# --- 4. EXECUTION ---
if __name__ == "__main__":
    
    # *** USER INPUT SECTION ***
    # --------------------------
    DATA_FILE_1M = "out_1m.csv"
    DATA_FILE_2M = "out_2m.csv"
    # --------------------------
    
    # 1. Load 1m data and assign true range of 1.0m
    X_1m, Y_1m = load_dataset(DATA_FILE_1M, true_range=1.0)
    
    # 2. Load 2m data and assign true range of 2.0m
    X_2m, Y_2m = load_dataset(DATA_FILE_2M, true_range=2.0)
    
    # 3. Combine datasets
    if X_1m.size > 0 and X_2m.size > 0:
        X_combined = np.concatenate((X_1m, X_2m), axis=0)
        Y_combined = np.concatenate((Y_1m, Y_2m), axis=0)
        
        print(f"\nTotal combined dataset size: {len(X_combined)} samples.")

        # Train and evaluate on the combined data
        trained_model = train_and_evaluate_svr(X_combined, Y_combined)
    elif X_1m.size > 0 or X_2m.size > 0:
         # Handle case where only one file loaded successfully
        print("\nWARNING: Only one file loaded successfully. Training on partial data.")
        X_combined = X_1m if X_1m.size > 0 else X_2m
        Y_combined = Y_1m if Y_1m.size > 0 else Y_2m
        trained_model = train_and_evaluate_svr(X_combined, Y_combined)
    else:
        print("\nModel training skipped because no data was loaded from either file.")
