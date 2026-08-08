import fs from "node:fs";
import path from "node:path";
import type { TestInfo } from "@playwright/test";

export type StrictPredictiveFixture = {
  filePath: string;
  rowCount: number;
  target: "bad_flag";
  specialValueColumns: readonly string[];
  missingValueColumns: readonly string[];
  dateColumn: "application_date";
};

function csvCell(value: string | number): string {
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

/**
 * Creates a deterministic, non-production classification dataset inside the
 * Playwright artifact root.  The fixture intentionally exercises every
 * preparation contract used by the strict Stage A acceptance:
 *
 * - exactly balanced binary target;
 * - unique record identifiers;
 * - numeric, categorical, and ISO-date predictors;
 * - ordinary nulls and extreme ordinary values;
 * - a strongly correlated numeric pair; and
 * - repeated -7/-8/-9 bureau-style sentinel codes.
 */
export function writeStrictPredictiveFixture(
  testInfo: TestInfo,
  rowCount = 1_200,
): StrictPredictiveFixture {
  const filePath = testInfo.outputPath("strict-predictive-workflow.csv");
  fs.mkdirSync(path.dirname(filePath), { recursive: true });

  const headers = [
    "record_id",
    "bad_flag",
    "age_years",
    "annual_income",
    "income_correlated",
    "utilization_pct",
    "inquiry_count",
    "recent_trade_count",
    "debt_to_income",
    "revolving_balance",
    "employment_type",
    "region",
    "application_date",
    "NetFractionInstallBurden",
    "PercentTradesNeverDelq",
    "MSinceMostRecentDelq",
  ] as const;

  const rows: string[] = [headers.join(",")];
  for (let index = 0; index < rowCount; index += 1) {
    // Keep every 20-row block exactly balanced while breaking the simple row
    // cycles used by categorical and bounded-count predictors.  An alternating
    // target made fields such as employment_type deterministic target sources,
    // so the governed authorization layer correctly excluded them and the
    // fixture could not exercise Validation Design's ordinary predictor path.
    const block = Math.floor(index / 20);
    const positionInBlock = index % 20;
    const target = ((positionInBlock * 7 + block * 3) % 20) < 10 ? 1 : 0;
    const age = 21 + ((index * 7) % 49);
    const baseIncome = 31_000 + ((index * 1_337) % 91_000) + target * 4_500;
    const annualIncome: string | number =
      index % 47 === 0
        ? ""
        : index % 113 === 0
          ? 510_000 + index * 31
          : baseIncome;
    const correlatedIncomeBasis =
      typeof annualIncome === "number" ? annualIncome : baseIncome;
    const correlatedIncome =
      Math.round(
        (correlatedIncomeBasis * 1.018 + ((index % 9) - 4) * 125) * 100,
      ) / 100;
    const utilization: string | number =
      index % 53 === 0
        ? ""
        : index % 127 === 0
          ? 246 + (index % 17)
          : Math.round((12 + ((index * 11) % 82) + target * 7.5) * 100) / 100;
    const inquiryCount = (index * 5 + target * 2) % 18;
    const recentTradeCount = 1 + ((index * 3 + target) % 14);
    const debtToIncome = Math.round((8 + ((index * 17) % 48) + target * 5.25) * 100) / 100;
    const revolvingBalance =
      index % 131 === 0
        ? 205_000 + index * 43
        : 500 + ((index * 719 + target * 4_000) % 58_000);
    const employment = index % 61 === 0
      ? ""
      : ["salaried", "self_employed", "hourly", "retired"][index % 4];
    const region = ["northeast", "south", "midwest", "west"][index % 4];
    const dayOffset = index % 730;
    const applicationDate = new Date(Date.UTC(2023, 0, 1 + dayOffset))
      .toISOString()
      .slice(0, 10);

    const installmentBurden =
      index % 11 === 0 ? [-7, -8, -9][index % 3] : (index * 7) % 101;
    const neverDelinquent = index % 17 === 0 ? -9 : (index * 13) % 101;
    const monthsSinceDelinquency =
      index % 19 === 0 ? [-7, -8, -9][index % 3] : (index * 5) % 145;

    rows.push(
      [
        `STRICT-${String(index + 1).padStart(5, "0")}`,
        target,
        age,
        annualIncome,
        correlatedIncome,
        utilization,
        inquiryCount,
        recentTradeCount,
        debtToIncome,
        revolvingBalance,
        employment,
        region,
        applicationDate,
        installmentBurden,
        neverDelinquent,
        monthsSinceDelinquency,
      ]
        .map(csvCell)
        .join(","),
    );
  }

  fs.writeFileSync(filePath, `${rows.join("\n")}\n`, "utf8");
  return {
    filePath,
    rowCount,
    target: "bad_flag",
    specialValueColumns: [
      "NetFractionInstallBurden",
      "PercentTradesNeverDelq",
      "MSinceMostRecentDelq",
    ],
    missingValueColumns: ["annual_income", "utilization_pct", "employment_type"],
    dateColumn: "application_date",
  };
}
