# USB PD Specification Parser

This Python script extracts and structures the **Table of Contents (ToC)** and document chunks from a USB Power Delivery (PD) specification PDF. It saves the extracted structure to a `.jsonl` file, useful for document understanding, indexing, or further analysis.

---

## 📁 Project Files

| File | Description |
|------|-------------|
| `usb_pd.py` | Main script that parses the USB PD spec PDF |
| `requirements.txt` | List of required Python packages |
| `usb_pd_output.jsonl` | Example output file (ToC entries in JSON Lines format) |
| `USB_PD_R3_2 V1.1 2024-10.pdf` | Input USB PD specification PDF |

---

## 🧰 Requirements

- Python 3.8 or higher
- pip (Python package installer)

---

## 📦 Install Dependencies

Open a terminal or command prompt in this project directory and run:

pip install -r requirements.txt
python usb_pd.py
