from openai import OpenAI

client = OpenAI(base_url="https://cdb8-152-57-37-211.ngrok-free.app/v1", api_key="not-needed")


response = client.chat.completions.create(
    model="qwen2.5:32b",  # ← Changed from qwen:32b
    messages=[{"role": "user", "content": "What is machine learning?"}]
)
print(response.choices[0].message.content)