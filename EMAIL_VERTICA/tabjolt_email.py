import vertica_python
import os
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import matplotlib.pyplot as plt
import boto3
from botocore.exceptions import NoCredentialsError


def load_config(config_file):
    with open(config_file, "r") as f:
        return json.load(f)


def download_from_s3(
    bucket_name, folder_path, s3_key, local_path,
    aws_access_key_id, aws_secret_access_key, region_name
):
    full_s3_key = f"{folder_path.strip('/')}/{s3_key}".lstrip("/")

    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name
        )
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        s3.download_file(bucket_name, full_s3_key, local_path)
        print(f"Downloaded {full_s3_key} to {local_path}")

    except NoCredentialsError:
        print("AWS credentials are unavailable.")
    except Exception as e:
        print(f"Error downloading S3 file: {e}")


def load_file_to_vertica(
    file_path, table_name, delimiter,
    skip_header=False, conn_info=None
):
    file_path = file_path.replace("\\", "/")
    skip_header_clause = "SKIP 1" if skip_header else ""

    copy_command = (
        "COPY {} FROM LOCAL '{}' DELIMITER '{}' {} "
        "REJECTED DATA 'rejected.txt';"
    ).format(table_name, file_path, delimiter, skip_header_clause)

    try:
        with vertica_python.connect(**conn_info) as connection:
            cur = connection.cursor()
            try:
                cur.execute(copy_command)
                connection.commit()
                print(f"Data loaded into {table_name}.")
            except vertica_python.errors.QueryError as e:
                print(f"Query error: {e}")
                connection.rollback()
            finally:
                cur.close()

    except vertica_python.errors.ConnectionError as e:
        print(f"Database connection error: {e}")


def execute_queries_with_messages(queries_with_messages, conn_info):
    query_results = []

    try:
        with vertica_python.connect(**conn_info) as connection:
            cur = connection.cursor()
            try:
                for query, message in queries_with_messages:
                    cur.execute(query)
                    results = cur.fetchall()
                    query_result = f"{message}\n"
                    for result in results:
                        query_result += f"{result[0]}\n"
                    query_results.append(query_result)
            except vertica_python.errors.QueryError as e:
                print(f"Query error: {e}")
            finally:
                cur.close()

    except vertica_python.errors.ConnectionError as e:
        print(f"Database connection error: {e}")

    return query_results


def create_average_time_graph(conn_info):
    try:
        with vertica_python.connect(**conn_info) as connection:
            cur = connection.cursor()
            try:
                cur.execute("""
                    SELECT summary_timestamp, summary_value
                    FROM demo_schema.summary_line
                    WHERE summary_metric = 'Avg'
                    ORDER BY summary_timestamp
                """)

                results = cur.fetchall()

                if not results:
                    print("No average-time results found.")
                    return None

                dates = [result[0] for result in results]
                values = [int(result[1]) for result in results]

                dates, values = zip(*sorted(zip(dates, values)))

                plt.figure(figsize=(10, 6))
                plt.plot(dates, values, marker="o", linestyle="-")
                plt.xlabel("Date")
                plt.ylabel("Average Time (ms)")
                plt.title("Average Processing Time by Day")
                plt.xticks(rotation=45)

                for date, value in zip(dates, values):
                    plt.annotate(
                        str(value),
                        (date, value),
                        textcoords="offset points",
                        xytext=(0, 10),
                        ha="center"
                    )

                plt.tight_layout()

                graph_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "output",
                    "average_time_graph.png"
                )

                os.makedirs(os.path.dirname(graph_path), exist_ok=True)
                plt.savefig(graph_path)
                plt.close()

                return graph_path

            except vertica_python.errors.QueryError as e:
                print(f"Query error: {e}")
            finally:
                cur.close()

    except vertica_python.errors.ConnectionError as e:
        print(f"Database connection error: {e}")

    return None


def send_email_with_graph(
    subject, query_results, graph_path,
    performance_samples_query, performance_samples_avg,
    performance_less_avg, conn_info, smtp_config
):
    sender = smtp_config["sender_email"]
    smtp_username = smtp_config["smtp_username"]
    smtp_password = smtp_config["smtp_password"]
    smtp_server = smtp_config["smtp_server"]
    smtp_port = smtp_config["smtp_port"]
    recipients = smtp_config["recipient_emails"]

    msg = MIMEMultipart("related")
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject

    html = f"""
    <html>
    <body>
        <h1>{subject}</h1>
        <p>Here are the results from the latest demo performance run.</p>
        <table border="1" cellpadding="8" cellspacing="0">
            <thead>
                <tr><th>Metric</th><th>Value</th></tr>
            </thead>
            <tbody>
    """

    for result in query_results:
        lines = result.split("\n")
        if len(lines) > 1:
            html += (
                f"<tr><td>{lines[0]}</td>"
                f"<td>{lines[1]}</td></tr>"
            )

    html += """
            </tbody>
        </table>
        <h3>Average Processing Time Graph</h3>
        <img src="cid:graph_cid" alt="Average Processing Time Graph">
    """

    def fetch_rows(query):
        with vertica_python.connect(**conn_info) as connection:
            cur = connection.cursor()
            try:
                cur.execute(query)
                return cur.fetchall()
            finally:
                cur.close()

    def append_table(title, headers, rows, highlight_percent=False):
        nonlocal html

        html += f"<h3>{title}</h3><table border='1' cellpadding='6'>"
        html += "<tr>" + "".join(
            f"<th>{header}</th>" for header in headers
        ) + "</tr>"

        for row in rows:
            html += "<tr>"
            for index, value in enumerate(row):
                if isinstance(value, float):
                    value = f"{value:.2f}"
                    if highlight_percent and index == len(row) - 1:
                        value += "%"

                style = ""
                if (
                    highlight_percent
                    and index == len(row) - 1
                    and isinstance(row[index], (int, float))
                    and row[index] > 20
                ):
                    style = "color:red;"

                html += f"<td style='{style}'>{value}</td>"

            html += "</tr>"

        html += "</table>"

    try:
        rows = fetch_rows(performance_samples_avg)
        append_table(
            "Performance Samples Above Average",
            [
                "Average Elapsed Time",
                "Current Elapsed Time",
                "Response Message",
                "Percentage Difference"
            ],
            rows,
            highlight_percent=True
        )
    except Exception as e:
        print(f"Error fetching above-average samples: {e}")

    try:
        rows = fetch_rows(performance_samples_query)
        append_table(
            "Performance Samples",
            [
                "Elapsed Time",
                "Latency",
                "Success Indicator",
                "Request Label",
                "Response Message"
            ],
            rows
        )
    except Exception as e:
        print(f"Error fetching performance samples: {e}")

    try:
        rows = fetch_rows(performance_less_avg)
        append_table(
            "Performance Samples Below Average",
            [
                "Average Elapsed Time",
                "Current Elapsed Time",
                "Response Message",
                "Percentage Difference"
            ],
            rows
        )
    except Exception as e:
        print(f"Error fetching below-average samples: {e}")

    html += "</body></html>"
    msg.attach(MIMEText(html, "html"))

    if graph_path and os.path.exists(graph_path):
        with open(graph_path, "rb") as f:
            img = MIMEImage(f.read())
            img.add_header("Content-ID", "<graph_cid>")
            img.add_header(
                "Content-Disposition",
                "inline",
                filename=os.path.basename(graph_path)
            )
            msg.attach(img)

    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(smtp_username, smtp_password)
            server.sendmail(sender, recipients, msg.as_string())

        print("Email sent successfully.")

    except Exception as e:
        print(f"Failed to send email: {e}")


if __name__ == "__main__":
    config = load_config("config.json")
    vertica_config = config["vertica"]
    smtp_config = config["smtp"]
    s3_config = config["s3"]

    base_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data"
    )
    os.makedirs(base_dir, exist_ok=True)

    files_to_download = [
        ("sample_counter.tsv", "sample_counter.tsv"),
        ("summary_line.csv", "summary_line.csv"),
        ("thread_details.csv", "thread_details.csv"),
        ("sample_performance.csv", "sample_performance.csv")
    ]

    for s3_key, filename in files_to_download:
        local_path = os.path.join(base_dir, filename)

        download_from_s3(
            s3_config["bucket_name"],
            s3_config.get("folder_path", ""),
            s3_key,
            local_path,
            s3_config["aws_access_key_id"],
            s3_config["aws_secret_access_key"],
            s3_config["region_name"]
        )

    files_to_load = [
        ("sample_counter.tsv", "demo_schema.sample_counter", "\t"),
        ("summary_line.csv", "demo_schema.summary_line", ","),
        ("thread_details.csv", "demo_schema.thread_details", "\t"),
        ("sample_performance.csv", "demo_schema.performance_samples", ",")
    ]

    for filename, table_name, delimiter in files_to_load:
        file_path = os.path.join(base_dir, filename)
        if os.path.exists(file_path):
            load_file_to_vertica(
                file_path,
                table_name,
                delimiter,
                skip_header=True,
                conn_info=vertica_config
            )
        else:
            print(f"File not found: {file_path}")

    queries_with_messages = [
        (
            "SELECT summary_value FROM demo_schema.summary_line "
            "WHERE summary_timestamp = CURRENT_DATE "
            "AND summary_metric = 'Avg'",
            "Average processing time (ms):"
        ),
        (
            "SELECT summary_value FROM demo_schema.summary_line "
            "WHERE summary_timestamp = CURRENT_DATE "
            "AND summary_metric = 'Max'",
            "Maximum processing time (ms):"
        ),
        (
            "SELECT summary_value FROM demo_schema.summary_line "
            "WHERE summary_timestamp = CURRENT_DATE "
            "AND summary_metric = 'Min'",
            "Minimum processing time (ms):"
        ),
        (
            "SELECT MAX(summary_timestamp) FROM demo_schema.sample_counter",
            "Latest demo test execution:"
        ),
        (
            "SELECT CAST(AVG(summary_value) AS INTEGER) "
            "FROM demo_schema.summary_line WHERE summary_metric = 'Avg'",
            "Historical average processing time (ms):"
        )
    ]

    performance_samples_query = """
        SELECT
            CAST(elapsed_time_ms AS INTEGER),
            latency_time_ms,
            success_indicator,
            request_label,
            response_message
        FROM demo_schema.performance_samples
        WHERE REGEXP_LIKE(timestamp_ms, '^[0-9]+$')
          AND TO_TIMESTAMP(CAST(timestamp_ms AS BIGINT) / 1000)
              >= CURRENT_DATE
        ORDER BY CAST(elapsed_time_ms AS INTEGER) DESC
    """

    performance_samples_avg = """
        SELECT
            avg_elapsed_ms,
            current_elapsed_ms,
            response_message,
            CASE
                WHEN avg_elapsed_ms = 0 THEN NULL
                ELSE ((current_elapsed_ms - avg_elapsed_ms)
                      / avg_elapsed_ms) * 100.0
            END AS percentage_difference
        FROM (
            SELECT
                historical.response_message,
                historical.avg_elapsed_ms,
                current_run.current_elapsed_ms
            FROM (
                SELECT
                    AVG(CAST(elapsed_time_ms AS INT)) AS avg_elapsed_ms,
                    response_message
                FROM demo_schema.performance_samples
                WHERE REGEXP_LIKE(elapsed_time_ms, '^[0-9]+$')
                GROUP BY response_message
            ) historical
            JOIN (
                SELECT
                    CAST(elapsed_time_ms AS INT) AS current_elapsed_ms,
                    response_message
                FROM demo_schema.performance_samples
                WHERE REGEXP_LIKE(timestamp_ms, '^[0-9]+$')
                  AND REGEXP_LIKE(elapsed_time_ms, '^[0-9]+$')
                  AND TO_TIMESTAMP(CAST(timestamp_ms AS BIGINT) / 1000)
                      >= CURRENT_DATE
            ) current_run
            ON historical.response_message =
               current_run.response_message
        ) samples
        WHERE avg_elapsed_ms < current_elapsed_ms
        ORDER BY percentage_difference DESC
    """

    performance_less_avg = """
        SELECT
            avg_elapsed_ms,
            current_elapsed_ms,
            response_message,
            percentage_difference
        FROM (
            SELECT
                historical.avg_elapsed_ms,
                current_run.current_elapsed_ms,
                current_run.response_message,
                CASE
                    WHEN historical.avg_elapsed_ms = 0 THEN NULL
                    ELSE (
                        (current_run.current_elapsed_ms
                         - historical.avg_elapsed_ms)
                        / historical.avg_elapsed_ms
                    ) * 100.0
                END AS percentage_difference
            FROM (
                SELECT
                    AVG(CAST(elapsed_time_ms AS INT)) AS avg_elapsed_ms,
                    response_message
                FROM demo_schema.performance_samples
                WHERE REGEXP_LIKE(elapsed_time_ms, '^[0-9]+$')
                GROUP BY response_message
            ) historical
            JOIN (
                SELECT
                    CAST(elapsed_time_ms AS INT) AS current_elapsed_ms,
                    response_message
                FROM demo_schema.performance_samples
                WHERE REGEXP_LIKE(timestamp_ms, '^[0-9]+$')
                  AND REGEXP_LIKE(elapsed_time_ms, '^[0-9]+$')
                  AND TO_TIMESTAMP(CAST(timestamp_ms AS BIGINT) / 1000)
                      >= CURRENT_DATE - INTERVAL '3 days'
            ) current_run
            ON historical.response_message =
               current_run.response_message
        ) samples
        WHERE percentage_difference < -40.0
        ORDER BY percentage_difference
    """

    query_results = execute_queries_with_messages(
        queries_with_messages,
        vertica_config
    )

    graph_path = create_average_time_graph(vertica_config)

    if query_results:
        send_email_with_graph(
            "Daily Demo Performance Summary",
            query_results,
            graph_path,
            performance_samples_query,
            performance_samples_avg,
            performance_less_avg,
            vertica_config,
            smtp_config
        )
