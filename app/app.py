# HTTP SERVER

import json

from flask import Flask, request
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from simulator import Simulator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from store import QRangeStore
import logging
from datetime import datetime
import time
from prometheus_client import (Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST)

#Total HTTP Requests by method/path/status
REQUEST_COUNT = Counter(
    "https_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"]
)

#Latency of HTTP request (seconds) by method/path
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Total HTTP requests",
    ["method", "path"]
)

#Duration of simulations specifically (seconds)
SIMULATION_DURATION = Histogram(
    "simulation_duration_seconds",
    "Duration of /simulation POST handler (seconds)"
)

class Base(DeclarativeBase):
    pass


############################## Application Configuration ##############################

app = Flask(__name__)
CORS(app, origins=["http://localhost:3030"])

db = SQLAlchemy(model_class=Base)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
db.init_app(app)

logging.basicConfig(level=logging.INFO)

############################## Database Models ##############################


class Simulation(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[str]


with app.app_context():
    db.create_all()

############################## Metrics ##############################

@app.before_request
def _start_timer():
    request._start_time = time.perf_counter()

@app.after_request
def _record_metrics(resp):
    try:
        start = getattr(request, "_start_time", None)
        if start is not None:
            latency = time.perf_counter() - start
            path = request.path or "/"
            REQUEST_LATENCY.labels(request.method, path).observe(latency)
            REQUEST_COUNT.labels(request.method, path, str(resp.status_code)).inc()
    except Exception:
        pass
    return resp

@app.get("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}

############################## API Endpoints ##############################


@app.get("/")
def health():
    return "<p>Sedaro Nano API - running!</p>"


@app.get("/simulation")
def get_data():
    # Get most recent simulation from database
    simulation: Simulation = Simulation.query.order_by(Simulation.id.desc()).first()
    return simulation.data if simulation else []


@app.post("/simulation")
def simulate():
    with SIMULATION_DURATION.time():
        # Get data from request in this form
        # init = {
        #     "Body1": {"x": 0, "y": 0.1, "vx": 0.1, "vy": 0},
        #     "Body2": {"x": 0, "y": 1, "vx": 1, "vy": 0},
        # }

        # Define time and timeStep for each agent
        init: dict = request.json or {}
        for key in init.keys():
            init[key]["time"] = 0
            init[key]["timeStep"] = 0.01

        # Create store and simulator
        t = datetime.now()
        store = QRangeStore()
        simulator = Simulator(store=store, init=init)
        logging.info(f"Time to Build: {datetime.now() - t}")

        # Run simulation
        t = datetime.now()
        simulator.simulate()
        logging.info(f"Time to Simulate: {datetime.now() - t}")

        # Save data to database
        simulation = Simulation(data=json.dumps(store.store))
        db.session.add(simulation)
        db.session.commit()

        return store.store
