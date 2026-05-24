/**
 * Vendor proposal volumes (FAR 15.204).
 *
 * Sealed in MongoDB GridFS until contract_modification deadline. Post-deadline,
 * CO unseals (atomic + audit-logged — touches Item 2 race surface).
 */
export interface ProposalVolume {
  volume: 'I_TECHNICAL' | 'II_PAST_PERFORMANCE' | 'III_PRICE';
  attachmentId: string;
  pageCount: number;
  submittedAt: string;
}

export interface Proposal {
  id: string;
  contract_modificationId: string;
  vendorId: string;
  vendorName: string;
  volumes: ProposalVolume[];
  submittedAt: string;
  sealedUntil: string;             // ISO — contract_modification deadline
  amendmentAcks: number[];         // acknowledged amendment numbers
}
