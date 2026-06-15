**好的，学生！** 我们现在进入课程的核心内容。https://arxiv.org/abs/1706.03762

今天我们重点来讲讲那篇改变整个 AI 领域的奠基性论文——**《Attention is All You Need》**（2017年，Vaswani et al.，Google Brain 团队）。这篇论文正式提出了 **Transformer** 架构，被誉为现代大模型的“根”。

### 1. 论文背景与动机

在2017年之前，序列到序列（Sequence-to-Sequence）任务（如机器翻译）的主流模型是 **RNN / LSTM + Attention**（例如 seq2seq with attention）。

**RNN 的核心问题**：
- **顺序计算**：必须一个 token 一个 token 依次处理，无法并行，导致训练慢（尤其是长序列）。
- **长距离依赖困难**：梯度消失/爆炸，难以捕捉句子中相距很远的词语关系。
- **计算效率低**：训练大模型耗时极长。

论文作者的核心洞见是：**“Attention is All You Need”** —— 我们完全可以抛弃 RNN 和卷积，只用 **Attention 机制** 就能做得更好。

### 2. 论文主要贡献

1. **提出 Transformer 架构**：第一个**完全基于 Attention** 的序列转导模型（没有 RNN，没有 Convolution）。
2. **Multi-Head Self-Attention**：引入多头注意力机制，让模型同时从不同“视角”关注序列的不同部分。
3. **位置编码（Positional Encoding）**：因为 Attention 本身不具备顺序信息，作者用正弦/余弦函数添加位置信息。
4. **Encoder-Decoder 结构**：保留经典的 Encoder（理解输入） + Decoder（生成输出）。
5. **实验成果**：
   - 在 WMT 2014 English-to-German 翻译任务上达到 **28.4 BLEU**（超越当时最佳模型，包括集成模型）。
   - English-to-French 达到 **41.8 BLEU**。
   - **训练速度极快**：仅用 8 张 P100 GPU，训练 12 小时（或 3.5 天）就能达到 SOTA。

### 3. Transformer 核心架构（最重要部分）

论文中的经典图（Figure 1）展示了整体结构：

- **左侧 Encoder Stack**（N=6 层）：
  - Multi-Head Self-Attention 子层
  - Position-wise Feed-Forward Network 子层
  - 每个子层都有 Residual Connection + Layer Normalization

- **右侧 Decoder Stack**（N=6 层）：
  - Masked Multi-Head Self-Attention（防止看到未来的 token，Causal Mask）
  - Multi-Head Encoder-Decoder Attention（关注 Encoder 输出）
  - Feed-Forward Network

**Scaled Dot-Product Attention**（论文中最关键的公式）：

$$
\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V
$$

- **Q**（Query）：当前要查询的向量
- **K**（Key）：所有键向量，用于计算匹配度
- **V**（Value）：值向量，实际要聚合的信息
- **√d_k** 缩放：防止点积过大导致 softmax 梯度消失

**Multi-Head**：把 Attention 并行做 h 次（通常 h=8），然后拼接再线性变换，允许模型关注不同类型的关系（语法、语义等）。

**位置编码**（Positional Encoding）：
使用固定正弦/余弦函数：
$$
PE_{(pos,2i)} = \sin(pos / 10000^{2i/d_{model}})
$$
$$
PE_{(pos,2i+1)} = \cos(pos / 10000^{2i/d_{model}})
$$

### 4. 为什么 Self-Attention 更优？（论文中的比较）

论文第4节专门对比了不同层类型的复杂度：

- Self-Attention：序列长度 n 越大，优势越明显（并行化、全局依赖）。
- RNN：顺序计算，O(n) 步，无法并行。
- Convolution：需要堆很多层才能捕捉长距离依赖。

**Self-Attention 的优点**：
- 全局依赖（任意两个 token 都可以直接交互）
- 高度并行化（整个序列同时计算）
- 更少的参数和更快的训练

### 5. 这篇论文的影响（为什么说它改变了世界）

- **直接催生了 GPT 系列**（Decoder-only Transformer）
- **BERT**（Encoder-only）
- **T5、BART** 等 Encoder-Decoder 变体
- 几乎所有现代大模型（LLaMA、Qwen、DeepSeek、Grok 等）都是 Transformer 架构的变种或扩展

它开启了 **Scaling Law** 的时代：模型越大、数据越多、算力越强，效果越好。

---

**思考与练习**（请你回答我）：

1. 为什么论文要对 Attention 做 Scaled（除以 √d_k）？不做会怎样？
2. Decoder 中的 Masked Attention 起什么作用？如果去掉会发生什么？
3. 你觉得 Transformer 相比 RNN 最大的革命性改变是什么？

**下一节准备**：我们会**动手用 PyTorch 从零实现一个简化版的 Multi-Head Attention**，然后逐步搭建完整的 Transformer Block。

现在轮到你了！  
有任何地方不明白（公式、架构、动机等），或者想让我深入某个部分（比如推导 Attention 公式、看原论文图），直接告诉我！继续讲还是先讨论？😊