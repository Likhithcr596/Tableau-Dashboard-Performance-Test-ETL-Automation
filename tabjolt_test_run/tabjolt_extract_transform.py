```python
import subprocess
import time
from datetime import datetime
import json
import os
import shutil
import csv
import boto3
from botocore.exceptions import NoCredentialsError, ClientError
import xml.etree.ElementTree as ET


# Load configuration from a JSON file
def load_config(config_file):
    with open(config_file, "r", encoding="utf-8") as file:
        return json.load(file)


# Copy the sample visualization pool file
def copy_vizpool_file(source_file, target_directory):
    if os.path.exists(source_file):
        os.makedirs(target_directory, exist_ok=True)
        shutil.copy(source_file, target_directory)
        print(f"Copied sample file to {target_directory}")
    else:
        print(f"Sample visualization file not found: {source_file}")


# Find the latest results folder containing a Windows counter file
def get_latest_results_directory(results_directory):
    if not os.path.isdir(results_directory):
        print("Results directory does not exist.")
        return None

    directories = [
        os.path.join(results_directory, item)
        for item in os.listdir(results_directory)
        if os.path.isdir(os.path.join(results_directory, item))
    ]

    if not directories:
        print("No result directories found.")
        return None

    return max(directories, key=os.path.getmtime)


# Copy the latest counter file and append a timestamp
def copy_latest_wincounter_file(results_directory, target_directory):
    latest_directory = get_latest_results_directory(results_directory)

    if not latest_directory:
        return None

    source_file = os.path.join(latest_directory, "wincounter.tsv")

    if not os.path.exists(source_file):
        print("No counter file found in the latest results directory.")
        return None

    os.makedirs(target_directory, exist_ok=True)
    output_file = os.path.join(target_directory, "sample_counter.tsv")
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(source_file, "r", encoding="utf-8") as infile, \
            open(output_file, "w", encoding="utf-8") as outfile:
        for line in infile:
            line = line.strip()
            if line:
                outfile.write(f"{line}\t{current_date}\n")

    print(f"Processed counter file saved to {output_file}")
    return output_file


# Parse thread details into a CSV file
def parse_threads_to_csv(log_file, output_csv):
    thread_details = []

    with open(log_file, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line.startswith("#"):
                thread_details.append(line)

    with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        for detail in thread_details:
            writer.writerow([detail])

    print(f"Thread details saved to {output_csv}")


# Parse summary metrics into a CSV file
def parse_summary_line_to_csv(log_file, output_csv):
    current_date = datetime.now().strftime("%Y-%m-%d")
    summary_values = {
        "Avg": "0",
        "Min": "0",
        "Max": "0",
        "Err": "0"
    }

    with open(log_file, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if line.startswith("summary ="):
                parts = line.split()

                try:
                    summary_values["Avg"] = parts[8].strip(",")
                    summary_values["Min"] = parts[10].strip(",")
                    summary_values["Max"] = parts[12].strip(",")
                    summary_values["Err"] = (
                        parts[14] + " " + parts[15].strip("()")
                    )
                except IndexError:
                    print("Summary line format is unexpected.")
                break

    with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        for metric in ("Avg", "Min", "Max", "Err"):
            writer.writerow([
                metric,
                summary_values[metric],
                current_date
            ])

    print(f"Summary metrics saved to {output_csv}")


# Parse a JTL result file into a CSV file
def parse_result_jtl_to_csv(jtl_file, output_csv):
    tree = ET.parse(jtl_file)
    root = tree.getroot()

    columns = [
        "t", "lt", "ts", "s", "lb", "rc",
        "rm", "tn", "dt", "by", "ng", "na"
    ]

    with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(columns)

        for sample in root.iter("sample"):
            writer.writerow([
                sample.get(column, "") for column in columns
            ])

    print(f"Sample results saved to {output_csv}")


# Run the configured performance test
def run_tabjolt_test(config):
    command = config["command"]
    directory = config["directory"]
    results_directory = config["results_directory"]
    target_directory = config["target_directory"]

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    output_file = f"demo_test_output_{timestamp}.txt"
    error_file = f"demo_error_log_{timestamp}.txt"

    print("Starting demo performance test...")
    start_time = time.time()

    try:
        process = subprocess.Popen(
            command,
            cwd=directory,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        stdout, stderr = process.communicate()

        with open(output_file, "w", encoding="utf-8") as file:
            file.write(stdout)

        if stderr:
            with open(error_file, "w", encoding="utf-8") as file:
                file.write(stderr)

        if process.returncode != 0:
            print(f"Test command failed with exit code {process.returncode}.")
            return

        print(f"Test output saved to {output_file}")
        print(f"Execution time: {time.time() - start_time:.2f} seconds")

        wincounter_file = copy_latest_wincounter_file(
            results_directory,
            target_directory
        )

        if not wincounter_file:
            print("Skipping result processing because no counter file was found.")
            return

        parse_threads_to_csv(output_file, "sample_thread_details.csv")
        parse_summary_line_to_csv(output_file, "sample_summary.csv")

        latest_directory = get_latest_results_directory(results_directory)

        if not latest_directory:
            return

        jtl_file = os.path.join(
            latest_directory,
            "sample-results.jtl"
        )

        if not os.path.exists(jtl_file):
            print("Sample JTL file was not found.")
            return

        parse_result_jtl_to_csv(jtl_file, "sample_workbook.csv")

        modify_workbook_csv(
            "sample_workbook.csv",
            "sample_performance.csv"
        )

        upload_files = [
            (wincounter_file, "sample_counter.tsv"),
            ("sample_thread_details.csv", "sample_thread_details.csv"),
            ("sample_summary.csv", "sample_summary.csv"),
            ("sample_performance.csv", "sample_performance.csv"),
            (output_file, os.path.basename(output_file))
        ]

        for local_file, remote_name in upload_files:
            upload_to_s3(
                local_file,
                config["s3_bucket"],
                config["folder_name"],
                remote_name,
                config["aws_access_key_id"],
                config["aws_secret_access_key"],
                config.get("region_name", "us-east-1")
            )

    except OSError as e:
        print(f"Unable to run the configured test command: {e}")


# Upload a file to the configured S3 bucket
def upload_to_s3(
    file_name,
    bucket,
    folder_name,
    s3_file_name,
    aws_access_key,
    aws_secret_key,
    region_name="us-east-1"
):
    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=region_name
        )

        s3_key = "/".join(
            part.strip("/")
            for part in (folder_name, s3_file_name)
            if part and part.strip("/")
        )

        s3.upload_file(file_name, bucket, s3_key)
        print(f"Uploaded file to demo S3 location: {s3_key}")
        return True

    except FileNotFoundError:
        print(f"File not found: {file_name}")
    except NoCredentialsError:
        print("AWS credentials are unavailable.")
    except ClientError as e:
        print(f"S3 upload failed: {e}")

    return False


# Add a sample site column to the result CSV
def modify_workbook_csv(input_csv, output_csv):
    if not os.path.exists(input_csv):
        print(f"Input file not found: {input_csv}")
        return

    with open(input_csv, "r", newline="", encoding="utf-8") as infile:
        lines = list(csv.reader(infile))

    if not lines:
        print(f"No data found in {input_csv}")
        return

    current_site_value = None
    modified_lines = []

    for row in lines:
        # The source format is expected to store site metadata in column 7.
        if len(row) > 6 and row[6].startswith("Site"):
            current_site_value = "Site: demo_site"

        modified_lines.append(
            row + [current_site_value if current_site_value else ""]
        )

    with open(output_csv, "w", newline="", encoding="utf-8") as outfile:
        writer = csv.writer(outfile)
        writer.writerows(modified_lines)

    print(f"Processed sample workbook saved to {output_csv}")


# Main entry point
def main():
    config_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "config.json"
    )

    config = load_config(config_file)

    copy_vizpool_file(
        config["vizpool_source_file"],
        config["vizpool_target_directory"]
    )

    run_tabjolt_test(config)


if __name__ == "__main__":
    main()
```
