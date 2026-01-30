import socket
import struct
import pygame
import math

# --- CONFIGURATION ---
UDP_IP = "0.0.0.0"  # Listen on all available interfaces
UDP_PORT = 4242     # Default SmoothTrack port
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 720
BOX_SCALE = 100     # Size of the 3D head box

# --- UDP SERVER SETUP ---
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setblocking(False) # Non-blocking to not freeze the game loop
try:
    sock.bind((UDP_IP, UDP_PORT))
    print(f"Listening for SmoothTrack on port {UDP_PORT}...")
except Exception as e:
    print(f"Error binding to port {UDP_PORT}: {e}")
    print("Make sure no other software (like OpenTrack) is using this port.")
    exit()

# --- 3D MATH HELPERS ---
def project_3d_point(x, y, z, width, height, scale):
    """Projects 3D coordinates to 2D screen space."""
    factor = 300 / (z + 400) # Simple perspective projection
    screen_x = x * factor * scale + width / 2
    screen_y = -y * factor * scale + height / 2
    return (int(screen_x), int(screen_y))

def rotate_point(x, y, z, pitch, yaw, roll):
    """Applies 3D rotation to a point."""
    # Convert degrees to radians
    pitch, yaw, roll = math.radians(pitch), math.radians(yaw), math.radians(roll)
    
    # Rotation math (Euler angles)
    # Yaw (around Y)
    nx = x * math.cos(yaw) - z * math.sin(yaw)
    nz = x * math.sin(yaw) + z * math.cos(yaw)
    x, z = nx, nz
    
    # Pitch (around X)
    ny = y * math.cos(pitch) - z * math.sin(pitch)
    nz = y * math.sin(pitch) + z * math.cos(pitch)
    y, z = ny, nz
    
    # Roll (around Z)
    nx = x * math.cos(roll) - y * math.sin(roll)
    ny = x * math.sin(roll) + y * math.cos(roll)
    x, y = nx, ny
    
    return x, y, z

# --- MAIN APP ---
def main():
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("SmoothTrack Python Viewer & Gaze Tracker")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Arial", 18)
    large_font = pygame.font.SysFont("Arial", 30)

    # State variables
    pose = [0.0] * 6 # x, y, z, yaw, pitch, roll
    running = True
    
    # Calibration State
    calibrating = False
    calib_step = 0 # 0: Top-Left, 1: Top-Right, 2: Bottom-Right, 3: Bottom-Left
    calib_points = [] # Stores (yaw, pitch) for each corner
    
    # Mapping bounds (defaults)
    min_yaw, max_yaw = -20, 20
    min_pitch, max_pitch = -20, 20

    print("App started. Ensure SmoothTrack is sending data to your PC's IP.")

    while running:
        # 1. READ UDP DATA
        try:
            while True: # Drain the buffer to get the latest packet
                data, addr = sock.recvfrom(1024)
                # OpenTrack standard is 6 doubles (48 bytes) -> x, y, z, yaw, pitch, roll
                if len(data) == 48:
                    pose = struct.unpack('dddddd', data)
        except BlockingIOError:
            pass # No new data
        
        # Unpack pose for clarity
        x, y, z, yaw, pitch, roll = pose
        
        # 2. HANDLE EVENTS
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_c:
                    calibrating = True
                    calib_step = 0
                    calib_points = []
                    print("Starting Calibration...")
                elif event.key == pygame.K_SPACE and calibrating:
                    # Record current Yaw/Pitch for the current corner
                    calib_points.append((yaw, pitch))
                    calib_step += 1
                    if calib_step > 3:
                        # Finish Calibration: Calculate bounds
                        # We average the "lefts" and "rights", "tops" and "bottoms" for stability
                        # Points order: TL, TR, BR, BL
                        
                        # Yaw increases to the Left (usually positive) or Right depending on config.
                        # We find min/max from the recorded corners.
                        yaws = [p[0] for p in calib_points]
                        pitchs = [p[1] for p in calib_points]
                        
                        min_yaw, max_yaw = min(yaws), max(yaws)
                        min_pitch, max_pitch = min(pitchs), max(pitchs)
                        
                        print(f"Calibration Done! Yaw Range: {min_yaw:.2f} to {max_yaw:.2f}")
                        calibrating = False

        # 3. DRAWING
        screen.fill((30, 30, 30)) # Dark gray background

        # -- DRAW HEAD BOX --
        # Define cube vertices
        vertices = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                    (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
        
        # Transform and project vertices
        proj_points = []
        for v in vertices:
            # Rotate
            rx, ry, rz = rotate_point(v[0], v[1], v[2], pitch, yaw, roll)
            # Translate (using input x,y,z)
            tx, ty, tz = rx + x/10, ry + y/10, rz - 5 # Push back 5 units so it's visible
            # Project
            proj_points.append(project_3d_point(tx, ty, tz, WINDOW_WIDTH, WINDOW_HEIGHT, BOX_SCALE))

        # Draw edges
        edges = [(0,1), (1,2), (2,3), (3,0), (4,5), (5,6), (6,7), (7,4), (0,4), (1,5), (2,6), (3,7)]
        for e in edges:
            pygame.draw.line(screen, (0, 255, 0), proj_points[e[0]], proj_points[e[1]], 2)
        
        # -- DRAW GAZE DOT --
        if not calibrating:
            # Normalize yaw/pitch to 0..1 based on calibration
            # Avoid division by zero
            yaw_range = (max_yaw - min_yaw) if (max_yaw - min_yaw) != 0 else 1
            pitch_range = (max_pitch - min_pitch) if (max_pitch - min_pitch) != 0 else 1
            
            # Map values. Note: Screen Y is often inverted relative to Pitch.
            # We assume calibration captured the direct correlation.
            norm_x = (yaw - min_yaw) / yaw_range
            norm_y = (pitch - min_pitch) / pitch_range
            
            # Clamp to screen
            screen_gaze_x = max(0, min(WINDOW_WIDTH, int(norm_x * WINDOW_WIDTH)))
            screen_gaze_y = max(0, min(WINDOW_HEIGHT, int(norm_y * WINDOW_HEIGHT)))
            
            # Invert axes if necessary (depending on SmoothTrack config, yaw might be inverted)
            # If the dot moves opposite to your head, swap 0 and WINDOW_WIDTH here.
            # For now, we trust the calibration points determined the direction.
            # To make it robust, we should interpolate based on the 4 known points (homography is best, but lerp is okay)
            
            # Simple lerp approach based on corners:
            # This handles inversion automatically if min_yaw corresponds to the right side, etc.
            # Re-calculating based on corners TL(0), TR(1), BR(2), BL(3)
            # X comes from Yaw, Y comes from Pitch
            
            if len(calib_points) == 4:
                # Interpolate X (Yaw)
                # Average Yaw for Left (TL, BL) and Right (TR, BR)
                yaw_left = (calib_points[0][0] + calib_points[3][0]) / 2
                yaw_right = (calib_points[1][0] + calib_points[2][0]) / 2
                
                # Interpolate Y (Pitch)
                # Average Pitch for Top (TL, TR) and Bottom (BL, BR)
                pitch_top = (calib_points[0][1] + calib_points[1][1]) / 2
                pitch_bottom = (calib_points[2][1] + calib_points[3][1]) / 2
                
                # Calculate percentages
                ratio_x = (yaw - yaw_left) / (yaw_right - yaw_left) if (yaw_right - yaw_left) != 0 else 0.5
                ratio_y = (pitch - pitch_top) / (pitch_bottom - pitch_top) if (pitch_bottom - pitch_top) != 0 else 0.5
                
                screen_gaze_x = int(ratio_x * WINDOW_WIDTH)
                screen_gaze_y = int(ratio_y * WINDOW_HEIGHT)
                
                pygame.draw.circle(screen, (255, 0, 0), (screen_gaze_x, screen_gaze_y), 15)

        # -- UI TEXT --
        if calibrating:
            steps = ["Top-Left", "Top-Right", "Bottom-Right", "Bottom-Left"]
            txt = large_font.render(f"LOOK AT {steps[calib_step]} and press SPACE", True, (255, 255, 0))
            screen.blit(txt, (WINDOW_WIDTH//2 - txt.get_width()//2, WINDOW_HEIGHT//2))
            
            # Draw marker for them to look at
            cx, cy = 0, 0
            if calib_step == 0: cx, cy = 20, 20
            elif calib_step == 1: cx, cy = WINDOW_WIDTH - 20, 20
            elif calib_step == 2: cx, cy = WINDOW_WIDTH - 20, WINDOW_HEIGHT - 20
            elif calib_step == 3: cx, cy = 20, WINDOW_HEIGHT - 20
            pygame.draw.circle(screen, (255, 255, 0), (cx, cy), 20)
            
        else:
            info = f"Yaw: {yaw:.1f} Pitch: {pitch:.1f} | Press 'C' to Calibrate"
            screen.blit(font.render(info, True, (255, 255, 255)), (10, 10))

        pygame.display.flip()
        clock.tick(60)

    sock.close()
    pygame.quit()

if __name__ == "__main__":
    main()