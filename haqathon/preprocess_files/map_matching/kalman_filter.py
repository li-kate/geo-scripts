"""
Kalman Filter & RTS Smoother for GPS Trajectory Cleaning
=========================================================

WHAT IS A KALMAN FILTER?
------------------------
A Kalman filter is a recursive algorithm that estimates the true state of a
system from noisy measurements. Think of it as a smart averaging process:

  - You have a **model** of how the thing moves (e.g., "a person walking
    continues at roughly the same velocity").
  - You have **measurements** (GPS readings) that are noisy.
  - The filter finds the optimal blend of "where the model predicts you are"
    and "where GPS says you are," weighted by how much you trust each.

For GPS cleaning, the state vector is [latitude, longitude, velocity_lat, velocity_lon].
The filter doesn't just average positions — it *infers velocity* from position
changes, then uses that velocity to predict the next position. This makes it
much better than simple averaging at handling gaps, noise spikes, and variable
sampling rates.

KEY CONCEPTS:
  - **State (x)**: Our best estimate of [position + velocity].
  - **Covariance (P)**: How uncertain we are about the state. Big P = unsure.
  - **Process noise (Q)**: How much the person's motion can change between
    measurements. Higher Q = "Expect lots of acceleration/deceleration.";
    Lower Q = "Velocity very stable; won't suddenly teleport or sprint at 50 mph."
  - **Measurement noise (R)**: How noisy the GPS is. Higher R = "GPS is very
    inaccurate, trust the model more."
  - **Kalman Gain (K)**: The magic ratio. K ≈ 1 means "trust GPS"; K ≈ 0
    means "trust the model." It's computed optimally from P, Q, and R.

WHAT IS RTS SMOOTHING?
----------------------
The standard Kalman filter is **causal** — it only uses past and present data.
When point #50 is processed, it doesn't know about point #51. This means
early points in the trajectory are estimated with less information than late ones.

The Rauch-Tung-Striebel (RTS) smoother fixes this with a **backward pass**.
After the forward Kalman pass processes all N points, the RTS smoother walks
backward from point N to point 1, propagating future information to past
estimates. The result:

  - Every point benefits from ALL data (past, present, AND future).
  - The trajectory is smoother and more accurate, especially at the start.
  - Sudden noise spikes get corrected from both directions.

The cost is that you must have all data before smoothing (can't do real-time),
which is fine for post-processing GPS traces.

Forward only:    point 1 uses [1] info, point 50 uses [1..50] info
After RTS:       point 1 uses [1..N] info, point 50 uses [1..N] info

WHY THIS MATTERS FOR MAP MATCHING:
-----------------------------------
Map matching (snapping GPS to roads/paths) works better with cleaner input.
A noisy GPS point 20m off the correct trail might get matched to the wrong
path. By running Kalman + RTS first, we bring that point closer to the true
position, making the map matcher's job easier and the result more accurate.
"""

import numpy as np


class KalmanFilter:
    """
    Constant Velocity Kalman Filter with RTS Smoother.

    Uses a 4D state: [latitude, longitude, velocity_lat, velocity_lon].

    The "constant velocity" model assumes the person maintains their current
    velocity between measurements. This is a reasonable approximation for
    walking/biking at typical GPS sampling rates (1-5 seconds). Acceleration
    is modeled as process noise — the filter allows for speed changes, it
    just doesn't predict them.

    Parameters
    ----------
    process_noise_std : float
        Controls how much velocity is allowed to change between steps.
        - Small (1e-5): Very smooth, good for steady walking. May lag behind
          actual turns.
        - Large (1e-3): Responsive to changes, but less smoothing of noise.
        For walking/biking GPS, 1e-5 to 1e-4 works well.

    measurement_noise_std : float
        How much we distrust GPS readings.
        - Small (1e-5): Trust GPS a lot (good for high-quality receivers).
        - Large (1e-3): Trust GPS less, rely more on motion model.
        Should roughly correspond to GPS accuracy in degrees. 1e-4 degrees
        ≈ 11 meters, which is typical consumer GPS accuracy.
    """

    def __init__(self, process_noise_std=0.05, measurement_noise_std=5.0):
        # --- State vector: [lat, lon, velocity_lat, velocity_lon] ---
        # Initialized to None; set on first measurement.
        self.x = None

        # --- State covariance matrix (4x4) ---
        # Diagonal = variance of each state component.
        # Large initial P means "we're very unsure about initial state."
        # The filter will quickly converge as measurements come in.
        self.P = np.eye(4) * 500.0

        # --- Measurement noise covariance (2x2) ---
        # Represents GPS accuracy. Only 2x2 because we only measure
        # position (lat, lon), not velocity. Velocity is inferred.
        self.R = np.eye(2) * (measurement_noise_std ** 2)

        # Process noise standard deviation (used to build Q matrix per step)
        self.q_std = process_noise_std

        # --- History storage for RTS backward pass ---
        # The RTS smoother needs the full history of predictions and updates
        # from the forward pass to correct them using future information.
        self.xs_updated = []   # State after each Kalman update (forward pass)
        self.Ps_updated = []   # Covariance after each update
        self.xs_pred = []      # State after each prediction (before update)
        self.Ps_pred = []      # Covariance after each prediction
        self.dt_history = []   # Time deltas (needed to reconstruct F matrices)

    def _get_Q(self, dt):
        """
        Build the process noise covariance matrix Q for a given time step.

        Uses the "discrete constant white noise" model, which assumes random
        acceleration that is constant within each time step. The math integrates
        continuous white noise acceleration over the time interval dt.

        The resulting Q has structure:
          Q = | dt^4/4  0      dt^3/2  0     |
              | 0       dt^4/4 0       dt^3/2| * q^2
              | dt^3/2  0      dt^2    0     |
              | 0       dt^3/2 0       dt^2  |

        Larger dt → larger Q → more uncertainty grows between measurements.
        This correctly handles variable GPS sampling rates: a 10-second gap
        produces more uncertainty than a 1-second gap.
        """
        q = self.q_std ** 2
        dt2 = dt ** 2
        dt3 = dt ** 3 / 2.0
        dt4 = dt ** 4 / 4.0
        return np.array([
            [dt4, 0, dt3, 0],
            [0, dt4, 0, dt3],
            [dt3, 0, dt2, 0],
            [0, dt3, 0, dt2]
        ]) * q

    def forward_step(self, measurement, dt):
        """
        One step of the forward Kalman filter.

        This is the classic predict-update cycle:

        PREDICT: "Based on our model, where should the person be now?"
          x_predicted = F * x  (position extrapolated by velocity * dt)
          P_predicted = F * P * F^T + Q  (uncertainty grows)

        UPDATE: "GPS says they're at <measurement>. Blend model and GPS."
          innovation = measurement - predicted_position
          K = optimal_blend_ratio(P_predicted, R)
          x_updated = x_predicted + K * innovation
          P_updated = (I - K*H) * P_predicted  (uncertainty shrinks)

        The Mahalanobis distance check provides "soft rejection" of outliers:
        if a GPS point is very far from the prediction (>3 sigma), we inflate
        the measurement noise for just that point. This means the filter mostly
        ignores the outlier without completely discarding it — a gentler
        approach than hard rejection.

        Parameters
        ----------
        measurement : list or array
            [latitude, longitude] from GPS
        dt : float
            Seconds since previous measurement

        Returns
        -------
        x : np.ndarray
            Updated state [lat, lon, v_lat, v_lon]
        """
        # --- Initialize on first measurement ---
        if self.x is None:
            self.x = np.array([measurement[0], measurement[1], 0, 0])
            self.xs_updated.append(self.x.copy())
            self.Ps_updated.append(self.P.copy())
            # Placeholders for first step (no prediction exists yet)
            self.xs_pred.append(self.x.copy())
            self.Ps_pred.append(self.P.copy())
            self.dt_history.append(dt)
            return self.x

        # --- State transition matrix F ---
        # Encodes the constant-velocity model:
        #   new_lat = old_lat + velocity_lat * dt
        #   new_lon = old_lon + velocity_lon * dt
        #   new_v_lat = old_v_lat  (velocity assumed constant)
        #   new_v_lon = old_v_lon
        F = np.eye(4)
        F[0, 2] = dt  # lat += v_lat * dt
        F[1, 3] = dt  # lon += v_lon * dt

        # --- Measurement matrix H ---
        # We observe only position, not velocity.
        # H extracts [lat, lon] from state [lat, lon, v_lat, v_lon].
        H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]])

        # Process noise for this time step
        Q = self._get_Q(dt)

        # ===================== PREDICT STEP =====================
        # Project state forward using motion model
        x_p = F @ self.x
        # Project uncertainty forward (grows due to process noise Q)
        P_p = F @ self.P @ F.T + Q

        # Save predictions (needed for RTS smoother backward pass)
        self.xs_pred.append(x_p.copy())
        self.Ps_pred.append(P_p.copy())
        self.dt_history.append(dt)

        # ===================== UPDATE STEP =====================
        # Innovation: difference between what GPS says and what model predicted
        y = np.array(measurement) - H @ x_p

        # Innovation covariance: total uncertainty in the innovation
        S = H @ P_p @ H.T + self.R
        inv_S = np.linalg.pinv(S)

        # --- Outlier detection via Mahalanobis distance ---
        # Mahalanobis distance measures how many "standard deviations" the
        # GPS reading is from the prediction, accounting for the shape of
        # the uncertainty ellipse. If > 3 sigma (squared > 9), the point
        # is suspiciously far from the prediction.
        #
        # Instead of hard-rejecting it (which loses data), we inflate R
        # proportionally. This makes the Kalman gain smaller, so the filter
        # mostly ignores the outlier while still slightly adjusting.
        mahalanobis_sq = y.T @ inv_S @ y

        if mahalanobis_sq > 9.0:  # 3-sigma squared
            # Soft rejection: inflate measurement noise for this point only
            S = H @ P_p @ H.T + (self.R * (mahalanobis_sq / 3.0))
            inv_S = np.linalg.pinv(S)

        # Kalman gain: the optimal blending weight
        # K ≈ 1: trust GPS (when model is uncertain or GPS is precise)
        # K ≈ 0: trust model (when GPS is noisy or model is confident)
        K = P_p @ H.T @ inv_S

        # Blend prediction with measurement
        self.x = x_p + K @ y

        # Update covariance (uncertainty shrinks after incorporating measurement)
        self.P = (np.eye(4) - K @ H) @ P_p

        # Save updated state (needed for RTS smoother)
        self.xs_updated.append(self.x.copy())
        self.Ps_updated.append(self.P.copy())

        return self.x

    def rts_smooth(self):
        """
        Rauch-Tung-Striebel (RTS) Backward Smoother.

        After the forward Kalman pass, this walks backward through time,
        correcting each estimate using information from future measurements.

        The math at each backward step:
          C = P_updated[t] * F^T * inv(P_predicted[t+1])
          x_smoothed[t] = x_updated[t] + C * (x_smoothed[t+1] - x_predicted[t+1])

        Intuitively: "How much did the next step's prediction differ from what
        we now know it should be? Propagate that correction backward."

        The smoother gain C determines how much future information influences
        past estimates. When the forward filter was very uncertain (large P),
        C is large and future data has a big corrective effect. When the forward
        filter was already confident, C is small and little correction is needed.

        Returns
        -------
        smoothed_xs : np.ndarray
            Array of smoothed state vectors, shape (N, 4)
        smoothed_Ps : np.ndarray
            Array of smoothed covariance matrices, shape (N, 4, 4)
        """
        num_steps = len(self.xs_updated)
        smoothed_xs = np.zeros_like(self.xs_updated)
        smoothed_Ps = np.zeros_like(self.Ps_updated)

        # The last point is already optimal (it used all forward data)
        smoothed_xs[-1] = self.xs_updated[-1]
        smoothed_Ps[-1] = self.Ps_updated[-1]

        current_smoothed_x = self.xs_updated[-1]
        current_smoothed_P = self.Ps_updated[-1]

        # Walk backward from second-to-last to first
        for t in range(num_steps - 2, -1, -1):
            # Reconstruct the transition matrix F that was used for step t → t+1
            dt = self.dt_history[t + 1]
            F = np.eye(4)
            F[0, 2] = dt
            F[1, 3] = dt

            # Smoother gain: how much to correct this step based on future info
            # C = P_updated[t] * F^T * inv(P_predicted[t+1])
            inv_P_pred = np.linalg.pinv(self.Ps_pred[t + 1])
            C = self.Ps_updated[t] @ F.T @ inv_P_pred

            # Correct state: add the propagated correction from the future
            # The term (smoothed[t+1] - predicted[t+1]) is the correction that
            # future data revealed was needed at step t+1. C propagates this
            # backward to step t.
            current_smoothed_x = self.xs_updated[t] + C @ (current_smoothed_x - self.xs_pred[t + 1])
            smoothed_xs[t] = current_smoothed_x

            # Correct covariance (uncertainty always decreases after smoothing)
            current_smoothed_P = self.Ps_updated[t] + C @ (current_smoothed_P - self.Ps_pred[t + 1]) @ C.T
            smoothed_Ps[t] = current_smoothed_P

        return smoothed_xs, smoothed_Ps


# =============================================================================
# LEGACY: Simple forward-only Kalman filter (no RTS smoothing)
# =============================================================================
# Kept for reference. The `update()` method provides a simpler interface
# for cases where RTS smoothing is not needed or real-time processing is
# required. The forward_step + rts_smooth approach above is preferred for
# post-processing GPS traces.
#
# import numpy as np
#
# class KalmanFilter:
#     """
#     Constant Velocity (CV) Kalman Filter.
#     State Vector x = [lat, lon, v_lat, v_lon].
#
#     Infers velocity from position changes to predict the next position more accurately.
#     """
#     def __init__(self, dt=1.0, process_noise_std=1e-4, measurement_noise_std=1e-4):
#         self.dt = dt # Time step (usually 1 second for GPS, but handled dynamically below)
#
#         # 1. State Vector [x, y, vx, vy]
#         # We start with zeros, will be initialized on first point
#         self.x = np.zeros(4)
#
#         # 2. State Transition Matrix (F)
#         # Relates current state to next state: pos = pos + vel*dt
#         self.F = np.eye(4)
#
#         # 3. Measurement Matrix (H)
#         # We only measure Position (Lat, Lon), not Velocity.
#         # So we extract the first 2 elements of the state.
#         self.H = np.array([
#             [1, 0, 0, 0],
#             [0, 1, 0, 0]
#         ])
#
#         # 4. Covariance Matrix (P)
#         # Initial uncertainty. We are unsure about initial velocity.
#         self.P = np.eye(4) * 1000.0
#
#         # 5. Process Noise (Q)
#         # Uncertainty in the model (e.g. driver changes speed).
#         # We trust the position update (low noise) but assume velocity can change (higher noise).
#         q_pos = process_noise_std**2
#         q_vel = process_noise_std**2
#         self.Q = np.eye(4)
#         self.Q[0,0] = q_pos
#         self.Q[1,1] = q_pos
#         self.Q[2,2] = q_vel
#         self.Q[3,3] = q_vel
#
#         # 6. Measurement Noise (R)
#         # Uncertainty in the sensor (GPS accuracy).
#         r_pos = measurement_noise_std**2
#         self.R = np.eye(2) * r_pos
#
#     def update(self, measurement, dt=None):
#         """
#         measurement: [lat, lon]
#         dt: time in seconds since last measurement.
#         """
#         if dt is not None:
#             # Update the F matrix dynamic time steps (crucial for real GPS data)
#             self.F[0, 2] = dt
#             self.F[1, 3] = dt
#
#         z = np.array(measurement)
#
#         # --- PREDICT STEP ---
#         # x_pred = F * x
#         x_pred = self.F @ self.x
#
#         # P_pred = F * P * F.T + Q
#         P_pred = self.F @ self.P @ self.F.T + self.Q
#
#         # --- UPDATE STEP ---
#         # Innovation (Residual): y = z - H * x_pred
#         y = z - self.H @ x_pred
#
#         # Innovation Covariance: S = H * P_pred * H.T + R
#         S = self.H @ P_pred @ self.H.T + self.R
#
#         # Kalman Gain: K = P_pred * H.T * inv(S)
#         K = P_pred @ self.H.T @ np.linalg.inv(S)
#
#         # New State: x = x_pred + K * y
#         self.x = x_pred + K @ y
#
#         # New Covariance: P = (I - K * H) * P_pred
#         self.P = (np.eye(4) - K @ self.H) @ P_pred
#
#         # Return smoothed coordinates [lat, lon]
#         return self.x[:2]