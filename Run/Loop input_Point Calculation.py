import json
import numpy as np
import serial


# --- Your existing functions remain here, no changes needed ---
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

# --- Main execution loop for UART input ---
def main():
    # Configure and open the serial port
    # Adjust 'COM3' to your serial port and 9600 to your baud rate.
    # The 'timeout' parameter prevents the program from hanging indefinitely.
    # 
    
    try:
        # Replace 'COM3' with your actual serial port name.
        ser = serial.Serial('COM3', baudrate=115200, timeout=1) 
        print(f"Listening for JSON data on {ser.name} at {ser.baudrate} bps...")
        
        # NOTE: You must provide the known coordinates for your anchors here.
        # These are placeholder values.
        known_anchor_coords = [
            np.array([0.0, 0.0, 0.0]),
            np.array([20.0, 0.0, 5.0]),
            np.array([0.0, 20.0, 10.0]),
            np.array([-10.0, -10.0, 2.0]),
            np.array([15.0,-5.0,12.0])
        ]
        
        while True:
            # Read a line from the serial port.
            # `readline()` blocks until a newline character is received.
            line = ser.readline()
            if line:
                try:
                    # Decode the line from bytes to a string
                    json_data_string = line.decode('utf-8').strip()
                    
                    # Ensure the line isn't empty after stripping whitespace
                    if not json_data_string:
                        continue
                    
                    # --- Your existing logic, now in a loop ---
                    data = json.loads(json_data_string)

                    poll_tx1_dtu = data['poll']['t_tx1_dtu']
                    dtu_per_second = data['time_base']['dtu_per_second']
                    anchors_data = data['anchors']

                    print(f"\n--- New Data Packet Received ---")
                    print(f"Poll TX1 DTU: {poll_tx1_dtu}")
                    print(f"DTU per Second: {dtu_per_second}")
                    
                    distances = []
                    valid_anchors = []

                    for anchor in anchors_data:
                        try:
                            distance = calculate_tof_and_distance(poll_tx1_dtu, anchor, dtu_per_second)
                            distances.append(distance)
                            # Get the corresponding anchor coordinates based on its aid
                            anchor_coord_index = anchor['aid'] - 1 # assuming aida are 1-based
                            if anchor_coord_index < len(known_anchor_coords):
                                valid_anchors.append(known_anchor_coords[anchor_coord_index])
                                print(f"Distance to Anchor {anchor['aid']}: {distance:.2f} meters")
                            else:
                                print(f"Warning: No known coordinates for Anchor {anchor['aid']}.")
                                distances.pop() # remove invalid distance
                                continue
                        except Exception as e:
                            print(f"Could not calculate distance for Anchor {anchor['aid']}: {e}")
                            distances.append(None)

                    # Filter out any None values from the list
                    valid_distances = [d for d in distances if d is not None]

                    if len(valid_distances) >= 4:
                        calculated_position = solve_multilateration(valid_anchors, valid_distances)
                        print("\n--- Multilateration Result ---")
                        print(f"Calculated Position: ({calculated_position[0]:.2f}, {calculated_position[1]:.2f}, {calculated_position[2]:.2f})")
                    else:
                        print("\nNot enough valid anchor data (at least 4 are needed) to perform 3D multilateration.")

                except json.JSONDecodeError:
                    print(f"Error: Invalid JSON format received: {line.decode('utf-8').strip()}")
                except Exception as e:
                    print(f"An error occurred during processing: {e}")

    except serial.SerialException as e:
        print(f"Error: Could not open serial port. Please check your port name and connection. Details: {e}")
    except KeyboardInterrupt:
        print("Program terminated by user.")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("Serial port closed.")

if __name__ == '__main__':
    main()