import streamlit as st
import snowflake.connector
import matplotlib.pyplot as plt
import numpy as np
import cv2
from pyzbar.pyzbar import decode
import qrcode
import os
import io
import tempfile
import boto3
import botocore
import botocore.exceptions


attendance_status = {}

# Snowflake connection parameters
CONNECTION_PARAMETERS = {
    "account": st.secrets["account"],
    "user": st.secrets["user"],
    "password": st.secrets["password"],
    "database": st.secrets["database"],
    "schema": st.secrets["schema"],
    "warehouse": st.secrets["warehouse"],
}
aws_access_key_id = st.secrets["access_key"]
aws_secret_access_key = st.secrets["secret_key"]
aws_region = st.secrets["region"]
s3 = boto3.client(
    "s3",
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    region_name=aws_region,
)


def generate_and_store_qr_codes():

    aws_access_key_id = st.secrets["access_key"]
    aws_secret_access_key = st.secrets["secret_key"]
    aws_region = st.secrets["region"]
    conn = snowflake.connector.connect(
        user=CONNECTION_PARAMETERS["user"],
        password=CONNECTION_PARAMETERS["password"],
        account=CONNECTION_PARAMETERS["account"],
        warehouse=CONNECTION_PARAMETERS["warehouse"],
        database=CONNECTION_PARAMETERS["database"],
        schema=CONNECTION_PARAMETERS["schema"],
    )
    cursor = conn.cursor()

    # Fetch attendee IDs and names from the EMP table
    cursor.execute("SELECT ATTENDEE_ID, NAME, QR_CODE FROM EMP")
    employee_data = cursor.fetchall()

    new_qr_codes_generated = 0  # Initialize the counter

    s3 = boto3.client(
        "s3",
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=aws_region,
    )

    for attendee_id, name, qr_code in employee_data:
        if qr_code:
            continue

        qr_data = f"{attendee_id} {name}"  # Combine ID and name in QR code data

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")

        # Save QR code image as temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
            qr_img.save(temp_file, format="PNG")

        # Upload QR code image to S3 bucket
        s3_file_name = f"qrcodes/{attendee_id}.png"
        s3.upload_file(temp_file.name, "qrstore", s3_file_name)

        # Clean up temporary file
        os.unlink(temp_file.name)

        # Update QR_CODE column with S3 file path
        s3_file_path = f"s3://qrstore/{s3_file_name}"
        update_query = "UPDATE EMP SET QR_CODE = %s WHERE ATTENDEE_ID = %s"
        cursor.execute(update_query, (s3_file_path, attendee_id))
        conn.commit()

        new_qr_codes_generated += 1  # Increment the counter
    cursor.close()
    conn.close()

    return new_qr_codes_generated



def mark_attendance(attendee_id):
    conn = snowflake.connector.connect(
        user=CONNECTION_PARAMETERS['user'],
        password=CONNECTION_PARAMETERS['password'],
        account=CONNECTION_PARAMETERS['account'],
        warehouse=CONNECTION_PARAMETERS['warehouse'],
        database=CONNECTION_PARAMETERS['database'],
        schema=CONNECTION_PARAMETERS['schema']
    )
    cursor = conn.cursor()

    print(f"Marking attendance for attendee ID: {attendee_id}")  # Debug print

    # Update attendance status
    update_query = "UPDATE EMP SET ATTENDED = TRUE WHERE ATTENDEE_ID = %s"
    try:
        cursor.execute(update_query, (attendee_id,))
        conn.commit()
        print("Attendance marked successfully.")  # Debug print
    except Exception as e:
        print(f"Error while marking attendance: {e}")  # Debug print
        conn.rollback()

    # Close the cursor and connection
    cursor.close()
    conn.close()



def query_attendance_data():
    conn = snowflake.connector.connect(
        user=CONNECTION_PARAMETERS['user'],
        password=CONNECTION_PARAMETERS['password'],
        account=CONNECTION_PARAMETERS['account'],
        warehouse=CONNECTION_PARAMETERS['warehouse'],
        database=CONNECTION_PARAMETERS['database'],
        schema=CONNECTION_PARAMETERS['schema']
    )
    cursor = conn.cursor()

    # Query attendance data
    cursor.execute("SELECT ATTENDEE_ID, ATTENDED FROM EMP")
    data = cursor.fetchall()

    cursor.close()
    conn.close()
    return data


# Function to generate attendance statistics
def generate_attendance_statistics(data):
    total_attendees = len(data)
    total_attended = sum(1 for _, attended in data if attended)
    total_not_attended = total_attendees - total_attended
    return {
        "Total Attendees": total_attendees,
        "Total Attended": total_attended,
        "Total Not Attended": total_not_attended,
    }


primary_color = "#007BFF"
secondary_color = "#6C757D"
st.set_page_config(
    page_title="NexusPassCheck",
    page_icon=":passport_control:",
    layout="wide",
)

# Streamlit app
st.title("NexusPassCheck")

# Custom menu options with emojis
menu_choices = {
    "QR Code Scanner": "📷 QR Code Scanner",
    "Attendance Statistics": "📊 Attendance Statistics",
    "Generate QR Codes": "🔐 Generate QR Codes",
    
}

menu_choice = st.sidebar.radio("Select Page", list(menu_choices.values()))
st.markdown(
    f"""
    <style>
        .sidebar .sidebar-content {{
            background-color: {secondary_color};
        }}
        .css-1aumxhk {{
            background-color: {primary_color};
        }}
    </style>
    """,
    unsafe_allow_html=True,)


if menu_choice == menu_choices["QR Code Scanner"]:
    st.header('QR Code Scanner')
    col1, col2 = st.columns([1, 2])

    # Display the camera feed from the back camera in the second column
    with col2:
        image = st.camera_input("Show QR code", key="qr_camera")

    if image is not None:
        bytes_data = image.getvalue()
        cv2_img = cv2.imdecode(np.frombuffer(bytes_data, np.uint8), cv2.IMREAD_COLOR)

        decoded_objects = decode(cv2_img)

        if decoded_objects:
            for obj in decoded_objects:
                qr_data = obj.data.decode('utf-8')
                # Split the QR data into attendee ID and name using only the first space
                qr_parts = qr_data.split(" ", 1)
                if len(qr_parts) == 2:
                    attendee_id, attendee_name = qr_parts
                else:
                    st.warning("Invalid QR code")
                    continue

                # Fetch the QR_CODE identifier and ATTENDED status from the Snowflake table based on the scanned QR data
                conn = snowflake.connector.connect(
                    user=CONNECTION_PARAMETERS['user'],
                    password=CONNECTION_PARAMETERS['password'],
                    account=CONNECTION_PARAMETERS['account'],
                    warehouse=CONNECTION_PARAMETERS['warehouse'],
                    database=CONNECTION_PARAMETERS['database'],
                    schema=CONNECTION_PARAMETERS['schema']
                )
                cursor = conn.cursor()

                cursor.execute(f"SELECT QR_CODE, ATTENDED FROM EMP WHERE ATTENDEE_ID = '{attendee_id}' AND NAME = '{attendee_name}'")
                row = cursor.fetchone()

                cursor.close()
                conn.close()

                # Define the default message before the loop
                message = 'QR code not found in the database.'
                if len(qr_parts) == 2:  # Only display QR data when format is valid
                    st.write(f"QR Code Data: {qr_data}")
                if row:
                    qr_code_identifier, attended = row
                    if qr_code_identifier:
                        if attended:
                            message = f'Attendance already marked for Attendee ID: {attendee_id}'
                        else:
                            # Mark attendance and update the Snowflake database
                            mark_attendance(attendee_id)  # Mark attendance for the attendee
                            message = f'QR code scanned successfully. Attendee marked as attended. Attendee ID: {attendee_id}'
                    else:
                        message = 'Invalid QR code.'

                st.write(message)

        else:
            st.warning("No QR code detected in the image. Please try again.")



elif menu_choice == menu_choices["Attendance Statistics"]:
    st.header("Attendance Statistics")

    # Query attendance data
    attendance_data = query_attendance_data()

    # Generate statistics
    statistics = generate_attendance_statistics(attendance_data)

    total_attended = statistics["Total Attended"]

    # Create a visually appealing and bold visualization for total attended
    st.write(
        f"<div style='text-align: center;'>"
        f"<h1 style='font-size: 4rem; color: green; font-weight: bold;'>{total_attended}</h1>"
        f"<p style='font-size: 1.5rem;'>Attended</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Add a divider to create separation
    st.markdown("<hr style='border-top: 2px solid #ccc;'>", unsafe_allow_html=True)

    # Create a pie chart for attendance breakdown
    plt.figure(figsize=(8, 6))

    labels = ["Attended", "Not Attended"]
    sizes = [total_attended, statistics["Total Not Attended"]]
    colors = ["#86bf91", "#e74c3c"]

    def func(pct, allvalues):
        absolute = int(pct / 100.0 * np.sum(allvalues))
        return "{:.1f}%\n({:d})".format(pct, absolute)

    plt.pie(sizes, labels=labels, colors=colors, autopct=lambda pct: func(pct, sizes))
    plt.axis("equal")  # Equal aspect ratio ensures the pie is circular.
    plt.title("Attendance Breakdown", fontsize=16)

    # Display the pie chart
    st.pyplot(plt)

elif menu_choice == menu_choices["Generate QR Codes"]:
    st.header("Generate QR Codes")
    st.write("Click the button below to generate QR codes for attendees.")

    if st.button("Generate QR Codes"):
        new_qr_codes_generated = generate_and_store_qr_codes()
        if new_qr_codes_generated > 0:
            st.success(
                f"{new_qr_codes_generated} new QR codes generated and stored successfully!"
            )
        elif new_qr_codes_generated == 0:
            st.info("No new QR codes generated. QR codes already exist for all attendees.")
        else:
            st.warning("QR codes could not be generated.")
