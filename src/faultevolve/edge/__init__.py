"""Local evaluation domain for the hybrid (cloud evolution + local evaluation) demo.

An edge device (the Android tablet data-centre twin) streams SMART telemetry over
the LAN to this machine. Raw rows, labels and per-disk predictions stay here; only
whitelisted aggregate metrics are ever packaged for the cloud.
"""
