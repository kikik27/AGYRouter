"""
Contoh Penggunaan AGY Local Proxy dengan OpenAI SDK & Agentic Pattern.
Dapat digunakan untuk menghubungkan framework seperti CrewAI, LangChain, AutoGen, LlamaIndex, dll.
"""

from openai import OpenAI

# Inisialisasi client OpenAI yang diarahkan ke proxy lokal kita
client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="local-proxy",  # Dummy key atau sesuai API_KEY di .env
)

def simple_chat():
    print("=== 1. Non-Streaming Chat ===")
    response = client.chat.completions.create(
        model="gemini-3.8-flash-high",
        messages=[
            {"role": "system", "content": "Anda adalah asisten AI yang ramah dan to the point."},
            {"role": "user", "content": "Jelaskan secara singkat apa itu Agentic AI dalam 2 kalimat."},
        ],
        stream=False,
    )
    print("Jawaban:\n", response.choices[0].message.content)


def streaming_chat():
    print("\n=== 2. Streaming Real-Time Tokens ===")
    stream = client.chat.completions.create(
        model="gemini-3.8-flash-high",
        messages=[
            {"role": "user", "content": "Buatkan daftar 3 prinsip utama agentic workflow."},
        ],
        stream=True,
    )

    print("Stream respons:")
    for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        print(delta, end="", flush=True)
    print("\n")


def multi_turn_agent_loop():
    print("\n=== 3. Multi-turn Agent Loop (Mempertahankan Memori) ===")
    user_session_id = "agent-session-42"

    # Turn 1
    print("Turn 1: Menyimpan state nama proyek")
    r1 = client.chat.completions.create(
        model="gemini-3.8-flash-high",
        messages=[
            {"role": "user", "content": "Proyek saya saat ini bernama 'Sistem Panen Cerdas'."}
        ],
        user=user_session_id,  # session ID untuk retensi memori
    )
    print("Agent:", r1.choices[0].message.content.strip())

    # Turn 2: Menanyakan kembali
    print("\nTurn 2: Menanyakan nama proyek dari memori sesi")
    r2 = client.chat.completions.create(
        model="gemini-3.8-flash-high",
        messages=[
            {"role": "user", "content": "Apa nama proyek saya yang baru saja saya sebutkan?"}
        ],
        user=user_session_id,  # Menggunakan session ID yang sama
    )
    print("Agent:", r2.choices[0].message.content.strip())


if __name__ == "__main__":
    print("Menghubungkan ke http://127.0.0.1:8000/v1 ...")
    try:
        simple_chat()
        streaming_chat()
        multi_turn_agent_loop()
    except Exception as e:
        print(f"Error: {e}")
        print("Pastikan proxy server telah dijalankan terlebih dahulu dengan: python run.py")
