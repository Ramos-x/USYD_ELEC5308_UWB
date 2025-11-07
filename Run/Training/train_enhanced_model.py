"""
Train Enhanced UWB Positioning Model
Use existing out_1m.csv and out_2m.csv data to train distance correction model
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from enhanced_positioning_model import (
    DistanceCorrectionModel,
    ChannelQualityFeatureExtractor
)

# Set font for plotting
plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


def main():
    print("=" * 80)
    print("Enhanced UWB Positioning System - Model Training")
    print("=" * 80)

    # 1. Data files and true distances
    csv_files = [
        'out_1m.csv',
        'out_1.5m.csv',
        'out_2m.csv',
        'out_2.5m.csv'
    ]

    true_distances = [
        1.0,  # out_1m.csv true distance is 1 meter
        1.5,
        2.0,  # out_2m.csv true distance is 2 meters
        2.5
    ]

    # Check if files exist
    script_dir = os.path.dirname(os.path.abspath(__file__))
    full_paths = []
    for csv_file in csv_files:
        full_path = os.path.join(script_dir, csv_file)
        if not os.path.exists(full_path):
            print(f"Error: File not found {full_path}")
            return
        full_paths.append(full_path)
        print(f"Found data file: {csv_file}")

    print(f"\nTrue distances: {true_distances}")

    # 2. Create model
    print("\n" + "=" * 80)
    print("Creating distance correction model...")
    model = DistanceCorrectionModel(model_type='gradient_boosting')

    # 3. Load training data
    print("\nLoading training data...")
    training_df = model.load_training_data(full_paths, true_distances)

    print(f"Total samples: {len(training_df)} records")
    print(f"Anchor distribution:")
    for aid in sorted(training_df['anchor_id'].unique()):
        count = len(training_df[training_df['anchor_id'] == aid])
        print(f"  Anchor {aid}: {count} records")

    # 4. Data statistical analysis
    print("\n" + "=" * 80)
    print("Data Statistical Analysis:")
    for aid in sorted(training_df['anchor_id'].unique()):
        anchor_data = training_df[training_df['anchor_id'] == aid]
        measured = anchor_data['measured_distance'].values
        true_dist = anchor_data['true_distance'].values

        error = measured - true_dist
        mae = np.mean(np.abs(error))
        std = np.std(error)

        print(f"\nAnchor {aid}:")
        print(f"  Measured distance - Mean: {np.mean(measured):.4f}m, Std: {np.std(measured):.4f}m")
        print(f"  Error - Mean: {np.mean(error):.4f}m, MAE: {mae:.4f}m, Std: {std:.4f}m")
        print(f"  Channel quality - SNR estimate: {np.mean(anchor_data['peak'] / anchor_data['acc']):.2f}")

    # 5. Train model
    print("\n" + "=" * 80)
    print("Starting model training...")
    results = model.train(training_df, n_estimators=200, max_depth=10)

    # 6. Output training results
    print("\n" + "=" * 80)
    print("Training Results Summary:")
    print("-" * 80)
    print(f"{'Anchor':<8} {'Samples':<10} {'MAE Before':<15} {'MAE After':<15} {'Improvement':<12}")
    print("-" * 80)

    for aid in sorted(results.keys()):
        r = results[aid]
        print(f"{aid:<8} {r['test_samples']:<10} "
              f"{r['test_mae_before']:<15.4f} {r['test_mae_after']:<15.4f} "
              f"{r['improvement']:<10.2f}%")

    # 7. Save model
    model_path = os.path.join(script_dir, 'uwb_distance_correction_model.pkl')
    model.save_model(model_path)

    # 8. Visualize results
    print("\n" + "=" * 80)
    print("Generating visualization plots...")

    # Create comparison plots for each anchor
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    fig.suptitle('Distance Correction Comparison', fontsize=16, fontweight='bold')

    for idx, aid in enumerate(sorted(results.keys())):
        if idx >= 5:
            break

        row = idx // 3
        col = idx % 3
        ax = axes[row, col]

        anchor_data = training_df[training_df['anchor_id'] == aid]

        # Extract features and predict
        corrected_distances = []
        for _, row_data in anchor_data.iterrows():
            channel_quality = {
                'peak': row_data['peak'],
                'pwr': row_data['pwr'],
                'fp_idx': row_data['fp_idx'],
                'acc': row_data['acc'],
                'xo': row_data['xo']
            }
            corrected = model.predict_correction(
                aid,
                row_data['measured_distance'],
                channel_quality
            )
            corrected_distances.append(corrected)

        measured = anchor_data['measured_distance'].values
        true_dist = anchor_data['true_distance'].values
        corrected = np.array(corrected_distances)

        # Plot scatter points
        ax.scatter(true_dist, measured, alpha=0.3, s=20, label='Before Correction', color='red')
        ax.scatter(true_dist, corrected, alpha=0.3, s=20, label='After Correction', color='blue')

        # Plot ideal line
        min_val = min(true_dist.min(), measured.min(), corrected.min())
        max_val = max(true_dist.max(), measured.max(), corrected.max())
        ax.plot([min_val, max_val], [min_val, max_val], 'k--', alpha=0.5, label='Ideal Line')

        ax.set_xlabel('True Distance (m)')
        ax.set_ylabel('Measured/Corrected Distance (m)')
        ax.set_title(f'Anchor {aid}')
        ax.legend()
        ax.grid(True, alpha=0.3)

    # Remove extra subplots
    if len(results) < 6:
        axes[1, 2].remove()

    plt.tight_layout()

    # Save plot
    plot_path = os.path.join(script_dir, 'correction_comparison.png')
    plt.savefig(plot_path, dpi=150, bbox_inches='tight')
    print(f"Plot saved to: {plot_path}")

    # 9. Create error distribution plots
    fig2, axes2 = plt.subplots(1, 2, figsize=(12, 5))
    fig2.suptitle('Error Distribution Comparison', fontsize=16, fontweight='bold')

    all_errors_before = []
    all_errors_after = []

    for aid in sorted(results.keys()):
        anchor_data = training_df[training_df['anchor_id'] == aid]

        corrected_distances = []
        for _, row_data in anchor_data.iterrows():
            channel_quality = {
                'peak': row_data['peak'],
                'pwr': row_data['pwr'],
                'fp_idx': row_data['fp_idx'],
                'acc': row_data['acc'],
                'xo': row_data['xo']
            }
            corrected = model.predict_correction(
                aid,
                row_data['measured_distance'],
                channel_quality
            )
            corrected_distances.append(corrected)

        measured = anchor_data['measured_distance'].values
        true_dist = anchor_data['true_distance'].values
        corrected = np.array(corrected_distances)

        errors_before = measured - true_dist
        errors_after = corrected - true_dist

        all_errors_before.extend(errors_before)
        all_errors_after.extend(errors_after)

    # Histogram
    axes2[0].hist(all_errors_before, bins=50, alpha=0.7, label='Before Correction', color='red')
    axes2[0].hist(all_errors_after, bins=50, alpha=0.7, label='After Correction', color='blue')
    axes2[0].set_xlabel('Error (m)')
    axes2[0].set_ylabel('Frequency')
    axes2[0].set_title('Error Distribution Histogram')
    axes2[0].legend()
    axes2[0].grid(True, alpha=0.3)

    # Box plot
    axes2[1].boxplot([all_errors_before, all_errors_after],
                     labels=['Before Correction', 'After Correction'])
    axes2[1].set_ylabel('Error (m)')
    axes2[1].set_title('Error Distribution Box Plot')
    axes2[1].grid(True, alpha=0.3)

    plt.tight_layout()
    error_plot_path = os.path.join(script_dir, 'error_distribution.png')
    plt.savefig(error_plot_path, dpi=150, bbox_inches='tight')
    print(f"Error distribution plot saved to: {error_plot_path}")

    print("\n" + "=" * 80)
    print("Training Complete!")
    print(f"Model file: {model_path}")
    print(f"Visualization results: {plot_path}, {error_plot_path}")
    print("=" * 80)

    # Display plots
    plt.show()


if __name__ == '__main__':
    main()
