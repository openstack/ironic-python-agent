# Use the official Centos image as the base image
FROM ubuntu:22.04

# Install necessary packages
RUN apt update -y && \
    apt install -y python3 python3-pip python3-venv && \
    apt clean all

WORKDIR /opt

# RUN python3 setup.py install

# Copy the application code to the container
# COPY dist/ironic_python_agent-8.2.0.dev171-py3-none-any.whl .

# RUN pip3 install ironic_python_agent-8.2.0.dev171-py3-none-any.whl

# Set the default command to run when starting the container
# CMD ["python3", "app.py"]
CMD ["sleep", "infinity"]
