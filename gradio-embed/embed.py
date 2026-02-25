import gradio as gr
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def embed_text(query: str):
    if not query or not query.strip():
        return {"data": []}
    embedding = model.encode(query).tolist()
    return {"data": [embedding]}

iface = gr.Interface(
    fn=embed_text,
    inputs=gr.Textbox(lines=2, placeholder="Enter text to embed..."),
    outputs="json",
    title="PSEBot Embedding Service",
    description="Returns 384-d embedding vector for input text.",
    allow_flagging="never"
)

if __name__ == "__main__":
    iface.launch(server_name="0.0.0.0", server_port=7860, share=True)