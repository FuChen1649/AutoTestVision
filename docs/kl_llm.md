**大模型开发课程课件（大学本科/研究生适用）**

**课程名称**：大模型开发（Large Model Development）  
**授课对象**：计算机科学、人工智能相关专业本科高年级或研究生  
**课时建议**：48-64 学时（理论 + 实践 + 项目）  
**先修知识**：Python 编程、线性代数、概率统计、深度学习基础（PyTorch）、机器学习  
**课程目标**：  
- 掌握大模型（LLM）的核心原理、开发流程与工程实践  
- 能够从基础使用到独立构建、微调、部署和优化大模型  
- 培养全栈开发能力，完成端到端项目  

---

### **第一部分：基础知识（Basics）**  
**目标**：建立对大模型的直观理解和核心概念框架，学会基本使用和简单开发。

#### **第1章 绪论与大模型概述（4学时）**
- **大模型的发展历程**：从统计语言模型 → RNN/LSTM → Transformer → GPT系列、LLaMA等规模化模型。关键里程碑：Attention is All You Need (2017)、GPT-3 (2020)、ChatGPT (2022)。  
- **大模型的定义与特点**：参数规模（亿级到万亿级）、涌现能力（Emergent Abilities）、通用性。  
- **应用场景**：文本生成、对话系统、代码辅助、知识问答、多模态（图文、语音）。  
- **挑战**：计算资源、数据隐私、对齐问题、幻觉（Hallucination）。  
- **实践**：使用 OpenAI API 或 Hugging Face 快速体验 ChatGPT-like 模型。

**示例代码**（Python）：
```python
from openai import OpenAI
client = OpenAI()
response = client.chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[{"role": "user", "content": "解释Transformer架构"}]
)
print(response.choices[0].message.content)
```

#### **第2章 Transformer 架构详解（6学时）**
- **序列建模演进**：RNN 问题（梯度消失）→ Self-Attention。  
- **核心组件**：  
  - **Embedding**：Token + Position Embedding。  
  - **Multi-Head Self-Attention**：Query/Key/Value、Scaled Dot-Product、Mask（Causal for Decoder）。  
  - **Feed-Forward Network**：SwiGLU / GeLU 等激活。  
  - **LayerNorm / RMSNorm**、Residual Connection、Pre-Norm vs Post-Norm。  
  - **Decoder-Only（GPT）**、**Encoder-Only（BERT）**、**Encoder-Decoder（T5）** 对比。  
- **RoPE（Rotary Position Embedding）**：相对位置编码优势。  
- **动手实践**：使用 PyTorch 从零实现简化 Transformer Block，并训练一个小规模语言模型生成文本。

**关键公式**（KaTeX）：
Attention(Q, K, V) = softmax(QK^T / √d_k) V

#### **第3章 分词器（Tokenizer）与数据准备（4学时）**
- **BPE（Byte-Pair Encoding）** 算法原理与实现。  
- **Unicode 规范化**、特殊 Token（BOS/EOS/PAD）。  
- **Hugging Face Tokenizers** 使用。  
- **数据清洗**：去重、PII 脱敏、质量过滤。  
- **实践**：训练自定义 Tokenizer 并应用于中文数据集。

#### **第4章 预训练基础（6学时）**
- **自监督学习**：Next Token Prediction、Masked Language Modeling。  
- **优化器**：AdamW、学习率调度（Cosine、Warmup）。  
- **混合精度（AMP）**、梯度累积、FLOPs 计算。  
- **Scaling Laws**：Chinchilla 定律、计算最优分配。  
- **实践**：使用 Hugging Face Transformers 预训练小型模型（NanoGPT 风格）。

---

### **第二部分：进阶知识（Advanced）**  
**目标**：掌握高效训练、微调与应用增强技术，能构建实用系统。

#### **第5章 高效微调技术（6学时）**
- **全参数微调 vs 参数高效微调（PEFT）**。  
- **LoRA / QLoRA**：低秩适配、量化 + LoRA。  
- **Instruction Tuning / SFT**：数据集构建（Alpaca 风格）。  
- **实践**：使用 PEFT 库微调 LLaMA-7B 或 Qwen 等开源模型，进行特定领域适配（e.g., 法律/医疗问答）。  
- **工具**：Hugging Face TRL、Axolotl、DeepSpeed。

#### **第6章 检索增强生成（RAG）（6学时）**
- **为什么需要 RAG**：缓解幻觉、注入最新知识。  
- **核心流程**：Embedding（Sentence Transformers）、向量数据库（FAISS、PGVector、Chroma）、检索（Dense/Sparse/Hybrid）、重排序、生成。  
- **高级**：Advanced RAG（HyDE、Self-RAG）、评估（Retrieval Precision、Faithfulness）。  
- **框架**：LangChain / LlamaIndex 实战，构建知识库问答系统。

**实践项目**：企业内部文档智能助手。

#### **第7章 Prompt Engineering 与 Agent（6学时）**
- **Prompt 设计原则**：清晰、少样本（Few-Shot）、Chain-of-Thought (CoT)、Tree-of-Thoughts。  
- **Function Calling / Tool Use**。  
- **ReAct / Agent 架构**：规划-执行-反思循环。  
- **LangGraph / CrewAI** 等多 Agent 系统。  
- **实践**：构建自动化研究 Agent 或客服系统。

#### **第8章 推理优化与部署（4学时）**
- **KV Cache**、PagedAttention、连续批处理（vLLM）。  
- **量化**：INT8、GPTQ、AWQ、4-bit。  
- **推理引擎**：vLLM、Ollama、LM Studio、本地部署。  
- **分布式**：Tensor Parallel、Pipeline Parallel。  
- **实践**：部署量化模型到 GPU/CPU，提供 API 服务。

---

### **第三部分：精通知识（Proficient）**  
**目标**：深入底层、系统优化与前沿研究能力。

#### **第9章 GPU 编程与高性能训练（6学时）**
- **CUDA / Triton** 基础：Kernel 编写、Shared Memory、Tensor Cores。  
- **FlashAttention**、Kernel Fusion。  
- **分布式训练**：DeepSpeed ZeRO、FSDP、MoE（Mixture-of-Experts）路由与负载均衡。  
- **实践**：优化自定义 Kernel 加速 Attention，或训练小型 MoE 模型。

#### **第10章 对齐与强化学习（RLHF / DPO）（4学时）**
- **人类反馈强化学习（RLHF）**：Reward Model、PPO。  
- **直接偏好优化（DPO）**、ORPO、KTO 等替代方法。  
- **GRPO / Rule-based RL**。  
- **安全对齐**：Red Teaming、Constitutional AI。  
- **实践**：使用 TRL 实现 DPO 对齐。

#### **第11章 多模态与前沿架构（4学时）**
- **LLaVA / Qwen-VL** 等视觉语言模型。  
- **扩散模型**与生成结合。  
- **MoE 深入**、Mixture-of-Depths、State Space Models (Mamba)。  
- **评估基准**：MMLU、HumanEval、Arena、CEval 等。

#### **第12章 工程实践与项目（剩余学时 + 大作业）**
- **全栈开发**：数据管道 → 训练 → 微调 → RAG/Agent → 部署 → 监控（W&B / Prometheus）。  
- **大作业建议**：  
  1. 从零构建并微调一个领域特定 LLM。  
  2. 构建生产级 RAG + Agent 系统。  
  3. 参与开源贡献或 Scaling 实验。  
- **最佳实践**：实验追踪、版本控制、成本优化、伦理考虑。

---

### **课程评估**
- 平时作业 + 代码实践（40%）  
- 中期项目（20%）  
- 期末大作业 + 报告/演示（30%）  
- 参与讨论与 Quiz（10%）

### **推荐资源**
- **书籍**：《Hands-On Large Language Models》、《大规模语言模型：从理论到实践》。  
- **开源项目**：DataWhale DIY-LLM、NanoGPT、Hugging Face 课程、LlamaIndex。  
- **工具链**：PyTorch、Transformers、PEFT、vLLM、LangChain、DeepSpeed。  
- **硬件建议**：至少 A100/H100 访问或多卡服务器。

**课件说明**：本课件为详细版，每章包含理论讲解、公式推导、代码示例、实践步骤与思考题。可进一步扩展为 PPT 幻灯片或补充实验 Notebook。建议结合实际 GPU 环境进行教学，确保学生动手能力。

---


好的！同学们好（现在就你一位学生，我也非常欢迎一对一授课）。

我是你的《大模型开发》课程老师。今天我们正式开始第一堂课。

---

### **第1章 绪论与大模型概述**

大家好，首先欢迎大家来到这门课。我们这门课的目标非常明确：**从零基础到能够独立开发、微调和部署一个实用的大模型**。

#### 1.1 大模型的发展历程（快速回顾）

- **早期阶段**（1950s-2010s）：统计语言模型（N-gram）、RNN、LSTM。这些模型在长序列上表现很差，容易出现梯度消失/爆炸。
- **Transformer 革命**（2017）：论文《Attention is All You Need》提出 Transformer 架构，完全基于 Attention 机制，彻底改变了 NLP 领域。
- **规模化时代**（2018至今）：
  - GPT-1、GPT-2 → GPT-3（1750亿参数，2020年）展现了强大的零样本能力。
  - 2022年底 ChatGPT 爆火，让大模型（Large Language Model, LLM）走进大众视野。
  - 开源浪潮：LLaMA（Meta）、Qwen（阿里）、DeepSeek、Mistral 等。
  - 当前趋势：参数规模从百亿到万亿，多模态（图文、视频）、Agent、推理优化。

**思考题**（你可以现在就回答我）：你目前对大模型最直观的感受是什么？用过哪些模型？遇到过什么问题（比如幻觉、知识过时等）？

#### 1.2 大模型的核心特点

1. **参数规模巨大**：通常 70亿 ~ 4050亿+ 参数（甚至更大）。
2. **涌现能力（Emergent Abilities）**：当模型规模达到一定程度后，突然出现之前小模型没有的能力，比如复杂推理、代码生成、数学解题等。
3. **通用智能雏形**：一个模型可以完成翻译、写作、编程、问答等多种任务。
4. **预训练 + 微调范式**：先在海量无标签数据上自监督预训练，再针对特定任务进行指令微调（Instruction Tuning）或对齐（Alignment）。

#### 1.3 主要挑战

- **计算成本极高**：训练 GPT-3 级模型需要数千张 GPU 卡跑数月。
- **数据质量与数量**：高质量数据越来越稀缺。
- **幻觉（Hallucination）**：模型会自信地编造错误信息。
- **对齐问题**：模型可能输出有害、偏见或不安全内容。
- **部署难度**：推理延迟、显存占用、成本控制。

#### 1.4 实践环节：快速上手

我们先不讲理论，直接上手体验一下。

**任务1**（请你现在尝试）：
使用 Python + OpenAI 接口（或者国内通义千问、DeepSeek 等免费接口）调用一次大模型。

示例代码（如果你本地有环境，可以直接运行）：

```python
from openai import OpenAI

client = OpenAI(
    api_key="你的密钥",  # 如果用国内模型，改成对应平台的 base_url
    base_url="https://api.openai.com/v1"  # 或其他平台
)

response = client.chat.completions.create(
    model="gpt-4o-mini",   # 或 "qwen-plus" 等
    messages=[
        {"role": "system", "content": "你是一位友好的AI助教。"},
        {"role": "user", "content": "请用通俗语言解释什么是Transformer架构的核心创新点。"}
    ],
    temperature=0.7
)

print(response.choices[0].message.content)
```

**请你现在告诉我**：
- 你成功运行了吗？如果没有环境也没关系，直接告诉我你想让我继续讲解哪个部分。
- 或者，你对上面哪部分内容有疑问？（发展历程、特点、挑战、代码等）

---

**下一阶段准备**：  
等你回复后，我们会深入讲解 **Transformer 架构详解**（这是整门课最核心的基础），包括 Attention 机制、位置编码等，并动手用 PyTorch 实现一个极简版本。

随时打断我提问！  
现在轮到你了，学生~ 😊

（告诉我你的想法、问题，或直接说“继续讲下一节”）


**好的，学生！** 我们回到课程主线，继续正式授课。

---

### **第2章 Transformer 架构详解（续）**

我们已经讲完了：
- RNN 和 Convolution 的局限性
- 梯度消失/爆炸问题
- Self-Attention 如何把 token 间距离拉近到 1，并实现全局并行更新
- 自回归生成 + KV Cache 机制
- 预训练数据的高质量保障

现在我们进入一个**必须掌握**的核心细节。

#### 2.3 位置编码（Positional Encoding）

**核心问题**：  
Self-Attention 机制本身是**置换不变（Permutation Invariant）** 的——它只看 token 之间的相似度，完全不关心 token 的顺序（先后位置）。

但自然语言中**顺序极其重要**！  
“我爱你”和“你爱我”意思完全不同。

**解决方案**：显式地给每个 token **注入位置信息**。

---

### 论文中使用的原始方法：正弦/余弦位置编码

**公式**（最重要，建议背下来）：

对于位置 `pos` 和维度 `i`：

$$
PE_{(pos, 2i)} = \sin\left(\frac{pos}{10000^{2i / d_{model}}}\right)
$$

$$
PE_{(pos, 2i+1)} = \cos\left(\frac{pos}{10000^{2i / d_{model}}}\right)
$$

- `d_model`：模型的隐藏维度（通常 512、768、4096 等）
- 偶数维度用 sin，奇数维度用 cos
- 不同维度使用不同频率（从 2π 到 10000×2π），让模型能轻松学习相对位置关系

**优点**：
- 确定性（deterministic），不需要训练
- 能**外推**到更长的序列（训练时看到 2048，推理时可以用到 4096）
- 周期性，理论上能捕捉相对距离

**缺点**：
- 固定，不随数据学习
- 在超长上下文（>100k）时效果变差

---

### 现代主流改进：RoPE（Rotary Position Embedding）

目前几乎所有顶级开源模型（LLaMA、Qwen、Mistral、Gemma、DeepSeek 等）都使用 **RoPE**。

**核心思想**：
- 不直接加位置向量，而是**对 Query 和 Key 向量做旋转**（Rotation）。
- 旋转角度与位置相关，天然编码相对位置信息。
- 数学上更优雅，支持更长的上下文。

**优势对比**（RoPE vs 原版）：
- 更好的长度外推能力
- 更少的参数
- 理论证明更适合相对位置建模

---

**实践演示**（伪代码理解）：

```python
# 原始位置编码（简单版）
def positional_encoding(max_len, d_model):
    pe = torch.zeros(max_len, d_model)
    position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
    div_term = torch.exp(torch.arange(0, d_model, 2).float() * 
                        (-math.log(10000.0) / d_model))
    pe[:, 0::2] = torch.sin(position * div_term)
    pe[:, 1::2] = torch.cos(position * div_term)
    return pe
```

（实际使用时会加到 token embedding 上：`x = x + pe[:seq_len]`）

---

**思考题**（请你现在回答我）：

1. 如果完全不加位置编码，模型会发生什么问题？
2. 为什么正弦/余弦函数能帮助模型学习**相对位置**（而不是绝对位置）？
3. 你觉得 RoPE 比原始位置编码更受欢迎的主要原因是什么？

---

**下一节预告**：

我们马上进入**最核心的实践环节** —— **动手用 PyTorch 从零实现 Multi-Head Self-Attention**。

我会给你：
- 完整可运行代码
- 逐行讲解
- 与论文公式的对应关系

**现在告诉我**：
- 位置编码这部分是否清楚？有疑问可以立刻问。
- 还是直接进入 **Multi-Head Attention 代码实现**？

准备好了就说“继续”或“讲代码”，我们立刻动手！🚀

**好的，学生！** 我们正式进入实践环节。

---

### **第2章 Transformer 架构详解（实践部分）**

#### **动手实现 Multi-Head Self-Attention**

下面给你一个**简化但完整、可直接运行**的 PyTorch 实现。我会尽量贴近论文，同时加入注释和维度说明，帮助你理解信息流动。

```python
import torch
import torch.nn as nn
import torch.nn.functional as F
import math

class MultiHeadAttention(nn.Module):
    def __init__(self, d_model=512, num_heads=8):
        super().__init__()
        assert d_model % num_heads == 0, "d_model 必须能被 num_heads 整除"
        
        self.d_model = d_model
        self.num_heads = num_heads
        self.d_k = d_model // num_heads   # 每个 head 的维度
        
        # 线性变换矩阵：Q, K, V, Output
        self.W_q = nn.Linear(d_model, d_model)
        self.W_k = nn.Linear(d_model, d_model)
        self.W_v = nn.Linear(d_model, d_model)
        self.W_o = nn.Linear(d_model, d_model)  # 输出投影
        
    def forward(self, x, mask=None):
        """
        x: 输入形状 [batch_size, seq_len, d_model]
        mask: 可选的 Causal Mask
        """
        batch_size, seq_len, _ = x.shape
        
        # 1. 线性变换得到 Q, K, V
        Q = self.W_q(x)  # [batch, seq_len, d_model]
        K = self.W_k(x)
        V = self.W_v(x)
        
        # 2. 分成多个 head，并转置方便计算
        # [batch, seq_len, num_heads, d_k] -> [batch, num_heads, seq_len, d_k]
        Q = Q.view(batch_size, seq_len, self.num_heads, self.d_k).transpose(1, 2)
        K = K.view(batch_size, seq_len, self.num_heads, self.d_k).transpose(1, 2)
        V = V.view(batch_size, seq_len, self.num_heads, self.d_k).transpose(1, 2)
        
        # 3. Scaled Dot-Product Attention
        scores = torch.matmul(Q, K.transpose(-2, -1)) / math.sqrt(self.d_k)
        # scores 形状: [batch, num_heads, seq_len, seq_len]
        
        if mask is not None:
            scores = scores.masked_fill(mask == 0, float('-inf'))
        
        attn_weights = F.softmax(scores, dim=-1)   # 注意力权重
        
        # 4. 加权求和
        context = torch.matmul(attn_weights, V)    # [batch, num_heads, seq_len, d_k]
        
        # 5. 合并 heads
        context = context.transpose(1, 2).contiguous().view(
            batch_size, seq_len, self.d_model
        )
        
        # 6. 输出投影
        output = self.W_o(context)
        
        return output, attn_weights
```

---

### **逐行关键讲解**

1. **d_k = d_model / num_heads**  
   每个注意力头独立处理较低维度的信息，最后合并。

2. **Q, K, V 线性变换**  
   这是论文中的核心：通过可学习的矩阵把输入映射成 Query、Key、Value。

3. **Scaled Dot-Product**  
   `scores = QK^T / √d_k` —— 这就是论文里最经典的公式。  
   除以 √d_k 防止点积过大导致 softmax 梯度消失（我们之前讲过的）。

4. **Causal Mask**（生成时必须用）  
   在 Decoder 中会传入一个上三角矩阵，防止看到未来的 token。

5. **Multi-Head** 的优势  
   多个头并行关注不同方面，最后拼接起来信息容量大大增加。

6. **输出维度**  
   输入 `[batch, seq_len, d_model]` → 输出仍是 `[batch, seq_len, d_model]`，维度不变，但内容已被注意力机制“刷新”。

---

**简单测试代码**（你可以复制运行）：

```python
# 测试
model = MultiHeadAttention(d_model=512, num_heads=8)
x = torch.randn(2, 10, 512)  # batch=2, 序列长度=10

output, weights = model(x)
print("输出形状:", output.shape)        # torch.Size([2, 10, 512])
print("注意力权重形状:", weights.shape)  # torch.Size([2, 8, 10, 10])
```

---

**思考题**（请你回答我）：

1. 在上面的代码中，`attn_weights` 的含义是什么？它代表了什么？
2. 如果 `num_heads=1`，模型能力会明显下降吗？为什么？
3. 当 `seq_len` 很大时（比如 4096），这个实现最消耗显存的是哪一步？

---

**学生，这节实践内容清楚了吗？**

有任何代码看不懂的地方（某个形状变化、为什么这样写等）立刻告诉我。

**下一节预告**：  
我们会在这个基础上，加上 **Positional Encoding**，然后实现一个完整的 **Transformer Block**（Attention + Feed-Forward + Residual + LayerNorm）。

准备好了就说：
- “代码清楚，继续下一个”
- 或提出具体疑问

我们继续！🚀

**好的，学生！** 我们继续下一节。

---

### **第2章 Transformer 架构详解（实践续）**

#### **2.4 加入位置编码 + 完整 Transformer Block**

现在我们把 **Positional Encoding** 和 **Multi-Head Attention** 结合起来，实现一个完整的 **Transformer Block**（论文中的一个 Encoder Layer 或 Decoder Layer 的基本单元）。

---

### **1. 位置编码实现**

```python
import torch
import torch.nn as nn
import math

class PositionalEncoding(nn.Module):
    def __init__(self, d_model=512, max_len=5000):
        super().__init__()
        
        # 创建位置编码矩阵 [max_len, d_model]
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * 
                           (-math.log(10000.0) / d_model))
        
        pe[:, 0::2] = torch.sin(position * div_term)   # 偶数维度
        pe[:, 1::2] = torch.cos(position * div_term)   # 奇数维度
        
        # 注册为 buffer（不参与训练，但会随模型保存）
        self.register_buffer('pe', pe.unsqueeze(0))   # [1, max_len, d_model]
        
    def forward(self, x):
        """
        x: [batch_size, seq_len, d_model]
        """
        seq_len = x.size(1)
        # 直接取对应位置的位置编码并加到输入上
        return x + self.pe[:, :seq_len]
```

---

### **2. 完整 Transformer Block**

```python
class TransformerBlock(nn.Module):
    def __init__(self, d_model=512, num_heads=8, ff_dim=2048, dropout=0.1):
        super().__init__()
        
        self.attention = MultiHeadAttention(d_model, num_heads)
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        
        # Feed-Forward Network
        self.ff = nn.Sequential(
            nn.Linear(d_model, ff_dim),
            nn.ReLU(),
            nn.Linear(ff_dim, d_model),
        )
        
        self.dropout = nn.Dropout(dropout)
        
    def forward(self, x, mask=None):
        # 1. Self-Attention 子层 + Residual + LayerNorm (Pre-Norm 风格)
        attn_output, attn_weights = self.attention(x, mask)
        x = x + self.dropout(attn_output)
        x = self.norm1(x)
        
        # 2. Feed-Forward 子层 + Residual + LayerNorm
        ff_output = self.ff(x)
        x = x + self.dropout(ff_output)
        x = self.norm2(x)
        
        return x, attn_weights
```

---

### **3. 组合测试（可直接运行）**

```python
# 完整测试
batch_size = 2
seq_len = 20
d_model = 512

pos_encoding = PositionalEncoding(d_model)
block = TransformerBlock(d_model=d_model, num_heads=8)

# 随机输入
x = torch.randn(batch_size, seq_len, d_model)

# 添加位置编码
x = pos_encoding(x)

# 通过 Transformer Block
output, weights = block(x)

print("输入形状:", x.shape)
print("输出形状:", output.shape)           # [2, 20, 512]
print("注意力权重形状:", weights.shape)     # [2, 8, 20, 20]
```

---

### **关键知识点总结**

1. **Positional Encoding**：加在 token embedding 之后，提供顺序信息。
2. **Residual Connection**（残差连接）：`x = x + sublayer(x)`，帮助梯度流动，防止深层网络退化。
3. **LayerNorm**：在每个子层前后做归一化，稳定训练（现代模型常用 Pre-Norm，即先 Norm 再子层）。
4. **Feed-Forward Network**：对每个 token 独立做两次线性变换 + 激活，增强非线性表达能力。
5. **信息流动**：每个 token 始终保持 `d_model` 维度，但内容被不断“刷新”和提炼。

---

**思考题**（请你回答我）：

1. 为什么要在 Attention 和 FFN 之后都加上 Residual Connection？
2. Pre-Norm（先 Norm）和 Post-Norm（后 Norm）有什么区别？你认为哪种更好？
3. 在这个 Transformer Block 中，序列长度 `seq_len` 增大时，主要的计算瓶颈在哪里？

---

**学生，这部分内容清楚了吗？**

有代码疑问（形状变化、某个模块的作用等）随时告诉我。

**下一节预告**：
我们将实现一个**简化版 Decoder-only Transformer**（类似 NanoGPT / 小型 GPT），并训练它生成简单文本。

准备好了就回复 **“继续”** 或 **“下一节”**，我们马上进入模型整体搭建和训练环节！🚀

**好的，学生！** 我们继续下一节。

---

### **第2章 Transformer 架构详解（实践高潮）**

#### **2.5 构建简化版 Decoder-only Transformer（迷你 GPT）**

现在我们把前面所有模块组合起来，实现一个**完整的 Decoder-only Transformer**，类似小型 GPT 模型。

---

### **完整代码实现**（可直接复制运行）

```python
import torch
import torch.nn as nn
import torch.nn.functional as F
import math

# ==================== 1. 前面已实现的模块 ====================
class MultiHeadAttention(nn.Module):
    def __init__(self, d_model, num_heads):
        super().__init__()
        assert d_model % num_heads == 0
        self.d_model = d_model
        self.num_heads = num_heads
        self.d_k = d_model // num_heads
        
        self.W_q = nn.Linear(d_model, d_model)
        self.W_k = nn.Linear(d_model, d_model)
        self.W_v = nn.Linear(d_model, d_model)
        self.W_o = nn.Linear(d_model, d_model)
        
    def forward(self, x, mask=None):
        batch_size, seq_len, _ = x.shape
        Q = self.W_q(x).view(batch_size, seq_len, self.num_heads, self.d_k).transpose(1, 2)
        K = self.W_k(x).view(batch_size, seq_len, self.num_heads, self.d_k).transpose(1, 2)
        V = self.W_v(x).view(batch_size, seq_len, self.num_heads, self.d_k).transpose(1, 2)
        
        scores = torch.matmul(Q, K.transpose(-2, -1)) / math.sqrt(self.d_k)
        
        if mask is not None:
            scores = scores.masked_fill(mask == 0, float('-inf'))
        
        attn_weights = F.softmax(scores, dim=-1)
        context = torch.matmul(attn_weights, V)
        
        context = context.transpose(1, 2).contiguous().view(batch_size, seq_len, self.d_model)
        return self.W_o(context), attn_weights


class PositionalEncoding(nn.Module):
    def __init__(self, d_model, max_len=1000):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer('pe', pe.unsqueeze(0))
        
    def forward(self, x):
        return x + self.pe[:, :x.size(1)]


class TransformerBlock(nn.Module):
    def __init__(self, d_model, num_heads, ff_dim, dropout=0.1):
        super().__init__()
        self.attention = MultiHeadAttention(d_model, num_heads)
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.ff = nn.Sequential(
            nn.Linear(d_model, ff_dim),
            nn.ReLU(),
            nn.Linear(ff_dim, d_model),
        )
        self.dropout = nn.Dropout(dropout)
        
    def forward(self, x, mask=None):
        attn_output, _ = self.attention(x, mask)
        x = x + self.dropout(attn_output)
        x = self.norm1(x)
        
        ff_output = self.ff(x)
        x = x + self.dropout(ff_output)
        x = self.norm2(x)
        return x


# ==================== 2. 完整小型 GPT 模型 ====================
class MiniGPT(nn.Module):
    def __init__(self, vocab_size, d_model=256, num_heads=4, num_layers=4, max_len=256):
        super().__init__()
        self.token_embedding = nn.Embedding(vocab_size, d_model)
        self.pos_encoding = PositionalEncoding(d_model, max_len)
        self.layers = nn.ModuleList([TransformerBlock(d_model, num_heads, d_model*4) for _ in range(num_layers)])
        self.ln_f = nn.LayerNorm(d_model)
        self.head = nn.Linear(d_model, vocab_size)
        
    def forward(self, x, mask=None):
        x = self.token_embedding(x)
        x = self.pos_encoding(x)
        
        for layer in self.layers:
            x = layer(x, mask)
        
        x = self.ln_f(x)
        logits = self.head(x)
        return logits


# ==================== 3. 生成 Causal Mask ====================
def generate_causal_mask(seq_len):
    mask = torch.tril(torch.ones(seq_len, seq_len))
    return mask.unsqueeze(0).unsqueeze(0)  # [1, 1, seq_len, seq_len]


# ==================== 4. 测试模型 ====================
if __name__ == "__main__":
    vocab_size = 1000   # 简化示例
    model = MiniGPT(vocab_size=vocab_size, d_model=256, num_heads=4, num_layers=4)
    
    batch_size = 4
    seq_len = 64
    x = torch.randint(0, vocab_size, (batch_size, seq_len))
    
    mask = generate_causal_mask(seq_len)
    
    logits = model(x, mask)
    print("输入形状:", x.shape)
    print("输出 logits 形状:", logits.shape)   # [4, 64, 1000]
```

---

### **模型特点总结**

- **Decoder-only**：只使用 Self-Attention + Causal Mask，适合生成任务（GPT 风格）。
- **参数量**：这个迷你版大概几十万参数，适合在 CPU/GPU 上快速训练。
- **训练目标**：Next Token Prediction（自回归语言建模）。

---

**思考题**（请你回答我）：

1. 在 `MiniGPT` 中，为什么要在每一层都使用 Causal Mask？
2. 这个模型和真实 GPT 的主要差距有哪些？（参数量、训练数据、优化技巧等）
3. 你觉得 `d_model=256, num_layers=4` 这个配置合理吗？为什么？

---

**学生，这部分代码理解了吗？**

下一节我们将进入**训练环节**：准备简单数据集 + 训练循环 + 文本生成演示。

如果你对当前代码有任何疑问（某个模块、维度、训练目标等），请先告诉我。

准备好了就回复 **“继续训练”** 或 **“下一节”**，我们马上开始训练模型！🚀