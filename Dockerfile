FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Jupyter and data science packages
RUN pip install --no-cache-dir \
    jupyter-server==2.16.0 \
    ipykernel==6.29.5 \
    ipython==9.2.0 \
    pandas \
    numpy \
    matplotlib \
    scipy \
    scikit-learn \
    pillow \
    plotly \
    seaborn \
    requests \
    beautifulsoup4 \
    sympy \
    && python -m ipykernel install --sys-prefix

# Set up server in /root/.server with its own venv
WORKDIR /root/.server
COPY server/ ./
RUN python -m venv .venv \
    && .venv/bin/pip install --no-cache-dir -r requirements.txt

# Jupyter config
RUN mkdir -p /root/.jupyter /root/.ipython/profile_default /root/.config/matplotlib
COPY jupyter_server_config.py /root/.jupyter/
COPY ipython_kernel_config.py /root/.ipython/profile_default/
COPY jupyter-healthcheck.sh /root/.jupyter/jupyter-healthcheck.sh
RUN chmod +x /root/.jupyter/jupyter-healthcheck.sh

# Minimal matplotlibrc (suppresses GUI backend warnings in headless env)
RUN echo "backend : Agg" > /root/.config/matplotlib/matplotlibrc

COPY start-up.sh /start-up.sh
RUN chmod +x /start-up.sh

WORKDIR /home/user

# FastAPI server is on 49999; Jupyter kernel API on 8888 (internal only)
EXPOSE 49999

CMD ["/start-up.sh"]
