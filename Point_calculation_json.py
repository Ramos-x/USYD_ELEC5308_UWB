import json
import numpy as np

def hex_to_dtu(hex_str):
    """Converts a hexadecimal string timestamp to a DTU integer."""
    if hex_str is None:
        return None
    return int(hex_str, 16)

def calculate_tof_and_distance(poll_tx1_dtu, anchor_data, dtu_per_second):
    """
    Calculates Time of Flight (ToF) and distance for a single anchor
    using the Double-Sided Two-Way Ranging (DS-TWR) method.
    """
    # Extract timestamps from the anchor data
    t_tx1_dtu = poll_tx1_dtu
    t_rx2_dtu = anchor_data['resp']['t_rx2_dtu']
    a_rx1_dtu = hex_to_dtu(anchor_data['resp']['a_rx1_hex'])
    a_tx2_dtu = hex_to_dtu(anchor_data['resp']['a_tx2_hex'])

    # DS-TWR formula for Time of Flight (ToF)
    # ToF = [(T_round1 - T_reply1) / 2]
    # where T_round1 is the tag's round trip time and T_reply1 is the anchor's reply time
    tof_dtu = ((t_rx2_dtu - t_tx1_dtu) - (a_tx2_dtu - a_rx1_dtu)) / 2

    # Convert ToF from DTU to seconds
    tof_seconds = tof_dtu / dtu_per_second

    # Calculate distance in meters
    speed_of_light = 299792458  # m/s
    distance_meters = tof_seconds * speed_of_light

    return distance_meters

def solve_multilateration(known_points, distances):
    """
    Calculates the position of a point in 3D based on its distances from multiple known points.
    This function uses a linearized least squares method.
    """
    n = len(known_points)
    if n < 4:
        raise ValueError("Multilateration requires at least 4 known points for a 3D solution.")

    # Use the last point as the reference to linearize the equations
    ref_point = known_points[n - 1]
    ref_dist = distances[n - 1]

    A = np.zeros((n - 1, 3))
    b = np.zeros((n - 1))

    for i in range(n - 1):
        pi = known_points[i]
        di = distances[i]

        A[i, 0] = 2 * (pi[0] - ref_point[0])
        A[i, 1] = 2 * (pi[1] - ref_point[1])
        A[i, 2] = 2 * (pi[2] - ref_point[2])
        
        b[i] = (ref_dist**2 - di**2) + \
               (pi[0]**2 - ref_point[0]**2) + \
               (pi[1]**2 - ref_point[1]**2) + \
               (pi[2]**2 - ref_point[2]**2)

    # Solve the system of linear equations
    calculated_position, residuals, rank, s = np.linalg.lstsq(A, b, rcond=None)
    
    return calculated_position

json_data_string = """
{
  "schema": "uwb.ds-twr@1",
  "epoch_id": "169d1a2e-1a2b-4f2c-9f01-00000001",
  "tag": {
    "id": 10,
    "fw": "tag-fw-1.0.0",
    "tick_ms": 12345
  },
  "radio": {
    "chan": 5,
    "prf": 64,
    "datarate": "6M8",
    "preamble": 128,
    "sfd": "DW",
    "antdelay_tx": 16456,
    "antdelay_rx": 16456
  },
  "time_base": {
    "unit": "dtu",
    "dtu_per_second": 63897600000,
    "wrap_bits": 40
  },
  "poll": {
    "seq": 42,
    "t_tx1_hex": "1A2B3C4D5E",
    "t_tx1_dtu": 112233445566
  },
  "anchors": [
    {
      "aid": 1,
      "slot": 0,
      "resp": {
        "t_rx2_hex": "1A2B3C4DEE",
        "t_rx2_dtu": 112233447566,
        "a_rx1_hex": "14",
        "a_tx2_hex": "7E4"
      },
      "final": {
        "t_tx3_plan_hex": "05361A51F4",
        "t_tx3_real_hex": "05361A9015"
      },
      "anc_report": {
        "a_rx3_hex": null,
        "range_mm": null
      },
      "quality": null
    },
    {
      "aid": 2,
      "slot": 1,
      "resp": {
        "t_rx2_hex": "1A2B3C4ED5",
        "t_rx2_dtu": 112233479637,
        "a_rx1_hex": "16",
        "a_tx2_hex": "7E6"
      },
      "final": {
        "t_tx3_plan_hex": "59418BAD70",
        "t_tx3_real_hex": "59418BEC15"
      },
      "anc_report": {
        "a_rx3_hex": null,
        "range_mm": null
      },
      "quality": null
    },
    {
      "aid": 3,
      "slot": 2,
      "resp": {
        "t_rx2_hex": "1A2B3C4F81",
        "t_rx2_dtu": 112233481245,
        "a_rx1_hex": "15",
        "a_tx2_hex": "7E5"
      },
      "final": {
        "t_tx3_plan_hex": "6F42023C32",
        "t_tx3_real_hex": "6F42029B35"
      },
      "anc_report": {
        "a_rx3_hex": null,
        "range_mm": null
      },
      "quality": null
    },
    {
      "aid": 4,
      "slot": 3,
      "resp": {
        "t_rx2_hex": "1A2B3C4E8A",
        "t_rx2_dtu": 112233476842,
        "a_rx1_hex": "13",
        "a_tx2_hex": "7E3"
      },
      "final": {
        "t_tx3_plan_hex": "8597479F3B",
        "t_tx3_real_hex": "8597480C14"
      },
      "anc_report": {
        "a_rx3_hex": null,
        "range_mm": null
      },
      "quality": null
    },
    {
      "aid": 5,
      "slot": 4,
      "resp": {
        "t_rx2_hex": "1A2B3C4EB7",
        "t_rx2_dtu": 112233477559,
        "a_rx1_hex": "11",
        "a_tx2_hex": "7E1"
      },
      "final": {
        "t_tx3_plan_hex": "9BD2F35954",
        "t_tx3_real_hex": "9BD2F3C966"
      },
      "anc_report": {
        "a_rx3_hex": null,
        "range_mm": null
      },
      "quality": null
    }
  ]
}
"""
try:
    data = json.loads(json_data_string)

    poll_tx1_dtu = data['poll']['t_tx1_dtu']
    dtu_per_second = data['time_base']['dtu_per_second']
    anchors_data = data['anchors']

    print(f"Poll TX1 DTU: {poll_tx1_dtu}")
    print(f"DTU per Second: {dtu_per_second}")
    print("\n--- Anchor Data Verification ---")

    for anchor in anchors_data:
        aid = anchor['aid']
        t_rx2_dtu = anchor['resp']['t_rx2_dtu']
        a_rx1_hex = anchor['resp']['a_rx1_hex']
        a_tx2_hex = anchor['resp']['a_tx2_hex']
        
        print(f"Anchor {aid}:")
        print(f"  t_rx2_dtu: {t_rx2_dtu}")
        print(f"  a_rx1_hex: {a_rx1_hex} -> a_rx1_dtu: {hex_to_dtu(a_rx1_hex)}")
        print(f"  a_tx2_hex: {a_tx2_hex} -> a_tx2_dtu: {hex_to_dtu(a_tx2_hex)}")
    
    print("\n--- Calculating Distances ---")

    distances = []
    for anchor in anchors_data:
        try:
            distance = calculate_tof_and_distance(poll_tx1_dtu, anchor, dtu_per_second)
            distances.append(distance)
            print(f"Distance to Anchor {anchor['aid']}: {distance:.2f} meters")
        except Exception as e:
            print(f"Could not calculate distance for Anchor {anchor['aid']}: {e}")
            distances.append(None)

    # --- Step 2: Set up and solve multilateration if enough data is available ---
    # NOTE: You must provide the known coordinates for your anchors here.
    # These are placeholder values.
    known_anchor_coords = [
    np.array([0.0, 0.0, 0.0]),
    np.array([20.0, 0.0, 5.0]),
    np.array([0.0, 20.0, 10.0]),
    np.array([-10.0, -10.0, 2.0]),
    np.array([15.0,-5.0,12.0])
]
    
    
    
    # Filter out anchors for which a valid distance could not be calculated
    valid_distances = [d for d in distances if d is not None]
    valid_anchors = [known_anchor_coords[i] for i, d in enumerate(distances) if d is not None]

    if len(valid_distances) >= 4:
        calculated_position = solve_multilateration(valid_anchors, valid_distances)
        print("\n--- Multilateration Result ---")
        print(f"Calculated Position: ({calculated_position[0]:.2f}, {calculated_position[1]:.2f}, {calculated_position[2]:.2f})")
    else:
        print("\nNot enough valid anchor data (at least 4 are needed) to perform 3D multilateration.")
        print("Please provide more anchor data in the JSON input.")

except json.JSONDecodeError:
    print("Error: Invalid JSON format.")
except Exception as e:
    print(f"An error occurred: {e}")


