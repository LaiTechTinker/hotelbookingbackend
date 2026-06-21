from fastapi import FastAPI

app=FastAPI(title="Lai hotel booking agent")

@app.get("/health")
def health_check():
    return{"status":"lai rest assured server is up and running!"}
