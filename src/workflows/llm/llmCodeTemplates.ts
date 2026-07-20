import type { LlmPageKey } from "./llmTypes";

export const llmCodeTemplates: Record<LlmPageKey, string[]> = {
  "use-case-risk": [
    "use_case = define_llm_boundary(users, allowed_actions, prohibited_actions)",
    "risk = classify_llm_risk(customer_impact, sensitive_data, autonomy_level)",
    "require_human_review_if(risk.level in ['high', 'regulated'])",
  ],
  sources: [
    "sources = register_source_inventory(files, owners, sensitivity, freshness)",
    "coverage = score_source_coverage(sources, required_topics)",
    "block_if_confidentiality_policy_missing(sources)",
  ],
  "task-schema": [
    "schema = build_json_schema(fields, labels, citations_required=True)",
    "validate_outputs_against_schema(model_outputs, schema)",
    "route_refusals_and_escalations(outputs, escalation_policy)",
  ],
  prompt: [
    "prompt_version = save_prompt(system_instruction, developer_instruction, examples)",
    "risk_scan = scan_instruction_conflicts(prompt_version)",
    "estimate_tokens(prompt_version)",
  ],
  rag: [
    "chunks = chunk_documents(sources, strategy=chunking_strategy)",
    "index = build_vector_index(chunks, embedding_model)",
    "retrieval_preview = retrieve(query, top_k=top_k, filters=metadata_filters)",
  ],
  "evaluation-dataset": [
    "eval_set = assemble_golden_cases(expected_answers, labels, citations, adversarial_prompts)",
    "coverage = evaluate_case_coverage(eval_set, risk_taxonomy)",
  ],
  "llm-evaluation": [
    "if llm_backend_available:",
    "    results = run_llm_evaluation(eval_set, prompt_version, retrieval_config)",
    "else:",
    "    results = manual_evaluation_template(eval_set)",
  ],
  safety: [
    "safety_results = run_red_team_suite(prompt_injection, leakage, hallucination, privacy)",
    "mitigations = map_safety_findings_to_controls(safety_results)",
  ],
  "human-review": [
    "review_policy = define_sampling_strategy(volume, risk_level, confidence)",
    "capture_overrides(review_events, rationale_required=True)",
  ],
  deployment: [
    "deployment_boundary = define_runtime_boundary(channel, users, rate_limits)",
    "monitoring = configure_llm_monitoring(thresholds, incident_policy)",
  ],
  recommendation: [
    "recommendation = approve_with_conditions(evaluation, safety, retrieval, human_review)",
    "persist_decision_record(recommendation, residual_risks)",
  ],
  documentation: [
    "package = assemble_llm_governance_package(prompt_registry, source_registry, evaluations)",
    "export_prompt_registry(package)",
    "export_source_inventory(package)",
  ],
};
