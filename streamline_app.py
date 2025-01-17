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

# Check for secrets before proceeding
def check_secrets():
    required_secrets = [
        'account',
        'user',
        'password',
        'warehouse',
        'database',
        'schema'
    ]
    
    missing_secrets = []
    for secret in required_secrets:
        if secret not in st.secrets:
            missing_secrets.append(secret)
    
    if missing_secrets:
        st.error("⚠️ Missing required configuration!")
        st.write("The following secrets are missing:")
        for secret in missing_secrets:
            st.write(f"- {secret}")
        st.write("Please add these to your .streamlit/secrets.toml file if running locally, or to your Streamlit Cloud secrets if deploying.")
        st.stop()

# Run the secrets check
check_secrets()

# If we get here, all required secrets are present
CONNECTION_PARAMETERS = {
    "account": st.secrets["account"],
    "user": st.secrets["user"],
    "password": st.secrets["password"],
    "database": st.secrets["database"],
    "schema": st.secrets["schema"],
    "warehouse": st.secrets["warehouse"],
}

def test_connection():
    try:
        conn = snowflake.connector.connect(**CONNECTION_PARAMETERS)
        cursor = conn.cursor()
        cursor.execute('SELECT current_version()')
        version = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return True, version
    except Exception as e:
        return False, str(e)

# UI Configuration
st.set_page_config(
    page_title="NexusPassCheck",
    page_icon=":passport_control:",
    layout="wide",
)

# Test the connection and show status
st.title("NexusPassCheck")

with st.sidebar:
    st.write("Connection Status:")
    success, result = test_connection()
    if success:
        st.success("✅ Connected to Snowflake")
        st.info(f"Version: {result}")
    else:
        st.error("❌ Connection Failed")
        st.error(f"Error: {result}")
        st.stop()

# Only show the menu if connection is successful
menu_choices = {
    "QR Code Scanner": "📷 QR Code Scanner",
    "Attendance Statistics": "📊 Attendance Statistics",
    "Generate QR Codes": "🔐 Generate QR Codes",
}

menu_choice = st.sidebar.radio("Select Page", list(menu_choices.values()))

# Your existing menu handling code here...
# (The rest of your application code remains the same)
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
