import json
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import os


def create_license_file(company_ntn_cnic, issue_date, expiry_date):
    """
    Utility function to create a signed license file.
    """
    try:
        # Example license data
        license_data = {
            "company_ntn_cnic": company_ntn_cnic,
            "issue": issue_date,
            "expiry": expiry_date,
        }

        # Load your private key
        private_key_path = os.path.join(os.path.dirname(__file__), "private.pem")
        with open(private_key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)

        # Create signature of license_data
        message = json.dumps(license_data, sort_keys=True).encode()
        signature = private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())

        # Add signature to license file
        license_data["signature"] = signature.hex()
        # Prepare the directory path: media/company_ntn_cnic/issue_expiry/
        dir_path = os.path.join(
            "media", "license_files", str(company_ntn_cnic), f"{issue_date}_{expiry_date}"
        )
        os.makedirs(dir_path, exist_ok=True)

        # Save the license file as license.key in the constructed directory
        license_file_path = os.path.join(dir_path, "license.key")

        # Get the file address from 'media' to 'license.key'
        path_return = os.path.relpath(license_file_path, start="media")
        with open(license_file_path, "w") as f:
            json.dump(license_data, f, indent=2)

        return [True, path_return]

    except Exception as e:
        return [False, f"Error creating license file: {e}"]
