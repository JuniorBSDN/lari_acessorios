from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import requests
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
CORS(app)

VERCEL_BLOB_READ_WRITE_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSOWORD")

def obter_conexao():
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or os.environ.get("POSTGRES_URL_NON_POOLING")
    
    if not db_url:
        raise ValueError("A string de conexão com o banco de dados não foi encontrada no ambiente da Vercel.")
    
    conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
    conn.autocommit = True
    return conn

def inicializar_infraestrutura_banco():
    try:
        conn = obter_conexao()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS produtos (
                id_produto VARCHAR(255) PRIMARY KEY,
                nome VARCHAR(255) NOT NULL,
                preco NUMERIC(10, 2) NOT NULL,
                categoria VARCHAR(100) NOT NULL,
                foto TEXT NOT NULL,
                visivel BOOLEAN DEFAULT TRUE
            );
        """)
        cursor.close()
        conn.close()
        print("✅ Banco de dados sincronizado.")
    except Exception as e:
        print(f"⚠️ Inicialização do banco: {str(e)}")

try:
    inicializar_infraestrutura_banco()
except Exception:
    pass

# Ajustado: O vercel.json já direciona o match de /api/admin/login para cá
@app.route("/api/admin/login", methods=["POST"])
@app.route("/admin/login", methods=["POST"])
def login_administrador():
    dados = request.get_json() or {}
    senha_enviada = dados.get("senha")

    senha_sistema = ADMIN_PASSWORD.strip() if ADMIN_PASSWORD else None
    senha_digitada = senha_enviada.strip() if senha_enviada else None

    if senha_sistema and senha_digitada == senha_sistema:
        return jsonify({"status": "success", "token": "Bearer sessao_valida_lari_premium"}), 200

    return jsonify({"error": "Senha incorreta!"}), 401

# Ajustado: Suporta o redirecionamento com ou sem o prefixo interpretado
@app.route("/api/upload", methods=["POST"])
@app.route("/upload", methods=["POST"])
def upload_foto():
    token_sessao = request.headers.get("Authorization")
    if token_sessao != "Bearer sessao_valida_lari_premium":
        return jsonify({"error": "Acesso não autorizado."}), 403

    if 'foto' not in request.files:
        return jsonify({"error": "Nenhum arquivo enviado."}), 400

    file = request.files['foto']
    if file.filename == '':
        return jsonify({"error": "Arquivo inválido."}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    content_type = file.content_type or "application/octet-stream"
    nome_id = f"produtos/produto_{os.urandom(4).hex()}{ext}"
    conteudo_binario = file.read()

    if not VERCEL_BLOB_READ_WRITE_TOKEN:
        return jsonify({"error": "Token de upload ausente no ambiente de execução."}), 500

    headers = {
        "Authorization": f"Bearer {VERCEL_BLOB_READ_WRITE_TOKEN}",
        "x-api-version": "1",
        "Content-Type": content_type
    }

    try:
        resposta = requests.put(f"https://blob.vercel-storage.com/{nome_id}", data=conteudo_binario, headers=headers)
        if resposta.status_code == 200:
            return jsonify({"url": resposta.json()["url"]}), 200
        return jsonify({"error": f"Erro Vercel Blob: {resposta.text}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Ajustado: Rotas duplicadas com e sem prefixo para blindar contra variações de proxy da Vercel
@app.route("/api/produtos", methods=["GET", "POST"])
@app.route("/produtos", methods=["GET", "POST"])
def gerenciar_produtos():
    if request.method == "POST":
        token_sessao = request.headers.get("Authorization")
        if token_sessao != "Bearer sessao_valida_lari_premium":
            return jsonify({"error": "Acesso não autorizado."}), 403

        dados = request.get_json() or {}
        id_produto = dados.get("id_produto")
        nome = dados.get("nome")
        preco = dados.get("preco")
        categoria = dados.get("categoria")
        foto = dados.get("foto")
        visivel = dados.get("visivel") if dados.get("visivel") is not None else True

        if not id_produto or not nome or preco is None or not foto:
            return jsonify({"error": "Campos incompletos ou foto ausente."}), 400

        try:
            conn = obter_conexao()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO produtos (id_produto, nome, preco, categoria, foto, visivel)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id_produto) DO UPDATE 
                SET nome = EXCLUDED.nome, preco = EXCLUDED.preco, 
                    categoria = EXCLUDED.categoria, foto = EXCLUDED.foto, visivel = EXCLUDED.visivel;
            """, (str(id_produto).strip(), nome, float(preco), categoria, foto, bool(visivel)))
            cursor.close()
            conn.close()
            return jsonify({"status": "success"}), 201
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    try:
        conn = obter_conexao()
        cursor = conn.cursor()
        cursor.execute("SELECT id_produto, nome, preco, categoria, foto, visivel FROM produtos ORDER BY nome ASC;")
        registros = cursor.fetchall()
        cursor.close()
        conn.close()

        for r in registros:
            r['preco'] = float(r['preco'])

        return jsonify(registros), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/produtos/<path:id_prod>", methods=["DELETE"])
@app.route("/produtos/<path:id_prod>", methods=["DELETE"])
def remover_produto_banco(id_prod):
    token_sessao = request.headers.get("Authorization")
    if token_sessao != "Bearer sessao_valida_lari_premium":
        return jsonify({"error": "Acesso não autorizado."}), 403

    id_limpo = str(id_prod).strip()

    try:
        conn = obter_conexao()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM produtos WHERE id_produto = %s;", (id_limpo,))
        cursor.close()
        conn.close()
        return jsonify({"status": "success", "message": f"Produto {id_limpo} removido com sucesso."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
