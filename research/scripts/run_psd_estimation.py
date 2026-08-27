
from pathlib import Path
import pickle
import dataclasses

from ebb.process.psd_compute import batch_estimate

def main():
    eeg_dir = Path("/media/matt/Data_A/leah/Kyunghee - KCNT1/KCNT1_Pre/standard")
    state_dir = Path("/media/matt/Data_A/leah/Kyunghee - KCNT1/KCNT1_Pre/sleep_export/chosen_csvs")

    # Optional inputs
    #swd_dir = Path("/media/matt/Data_A/leah/Pipeline_test/swd_ts")
    #drink_dir = Path("/media/matt/Data_A/leah/Pipeline_test/drink_mask")

    out_path = Path("/media/matt/Data_A/leah/Kyunghee - KCNT1/KCNT1_Pre/psd/psds_state_prob_trial.pkl")

    results = batch_estimate(
        eeg_dir=eeg_dir,
        state_dir=state_dir,
        swd_dir=None,          # set to None if not using SWD
        drink_dir=None,      # set to None if not using drink masks
        ncores=6,
        fs=250,
        nstd=5,
        verbose=True,
        s_prob = 0.99,
    )

    print(f"Computed {len(results)} PSD results")

    # To Save Results as dictionary
    r = [dataclasses.asdict(result) for result in results]

    with open(out_path, "wb") as f:
        pickle.dump(r, f)

    print(f"Saved results to {out_path}")

if __name__ == "__main__":
    main()
